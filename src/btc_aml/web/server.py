"""Local HTTP server for the control panel (standard library only).

It listens on 127.0.0.1, so it is reachable only from this computer. Pages are rendered
on the server; forms post back and are redirected (post/redirect/get), so refreshing a
page never starts an analysis twice.
"""

from __future__ import annotations

import csv
import io
import re
import socketserver
from datetime import UTC, date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import httpx

from btc_aml.config import AppConfig
from btc_aml.data_sources.ecb import load_ecb_rates
from btc_aml.data_sources.http import DataSourceError
from btc_aml.data_sources.labels import (
    COLUMNS,
    ImportResult,
    LabelError,
    import_labels,
    read_labels,
)
from btc_aml.data_sources.ofac import OfacError, load_ofac_list
from btc_aml.runner import BlockRangeError, check_transaction
from btc_aml.screening import Screener
from btc_aml.services import Services
from btc_aml.web import render
from btc_aml.web.jobs import JobRunner
from btc_aml.web.runs import RunNotFoundError, list_runs, load_run, run_file, save_review

MAX_FORM_BYTES = 200_000
RUN_PATH = re.compile(r"^/runs/(?P<run_id>[^/]+)(?P<rest>/.*)?$")


class ControlPanel:
    """State shared by all requests: configuration, the task runner, the last reviewer."""

    def __init__(self, config: AppConfig, transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        self.transport = transport  # tests replace the network here
        self.jobs = JobRunner(config, transport)
        self.reviewer = ""
        self._tip: int | None = None
        self._tip_checked = False

    def status(self) -> dict[str, Any]:
        config = self.config
        try:
            ofac = load_ofac_list(config.ofac_local_path)
            ofac_status: dict[str, Any] | None = {
                "publish_date": ofac.publish_date,
                "downloaded_at": ofac.downloaded_at,
                "addresses": len(ofac.addresses),
            }
        except OfacError:
            ofac_status = None
        fx = load_ecb_rates(config.fx_local_path)
        try:
            labels = len(read_labels(config.labels_path))
        except LabelError:
            labels = 0
        return {
            "ofac": ofac_status,
            "fx": f"Version {fx.version}" if fx else None,
            "labels": labels,
            "labels_path": str(config.labels_path),
            "rules_version": config.rules_version,
            "config_hash": config.config_hash,
            "max_blocks": config.max_blocks,
            "tip": self.tip_height(),
        }

    def tip_height(self) -> int | None:
        """Latest block height, fetched once per session (only a hint for the form)."""
        if not self._tip_checked:
            self._tip_checked = True
            try:
                with self.services() as services:
                    self._tip = services.esplora.get_tip_height()
            except DataSourceError:
                self._tip = None
        return self._tip

    def import_labels_text(self, text: str) -> ImportResult:
        """Validate pasted CSV text and merge it into the labels file (all or nothing)."""
        inputs = self.config.output_dir / "ui_inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        path = inputs / f"labels_{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.csv"
        path.write_text(text.strip() + "\n", encoding="utf-8")
        try:
            return import_labels(path, self.config.labels_path)
        except LabelError as exc:  # the temporary file name means nothing to the user
            raise LabelError(str(exc).replace(f"{path}: ", "")) from exc

    def services(self) -> Services:
        return Services.from_config(self.config, transport=self.transport)


def single_label_csv(form: dict[str, str]) -> str:
    """CSV text (header + one row) for a label entered in the form."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    writer.writerow([form.get(column, "").strip() for column in COLUMNS])
    return buffer.getvalue()


def make_handler(panel: ControlPanel) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "btc-aml-monitor"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib name
            pass  # keep the terminal quiet; runs have their own logs

        # --- GET ----------------------------------------------------------------------

        def do_GET(self) -> None:  # noqa: N802 - stdlib name
            url = urlparse(self.path)
            query = parse_qs(url.query)
            output_dir = panel.config.output_dir
            try:
                if url.path == "/":
                    message = query.get("error", [""])[0]
                    runs = list_runs(output_dir)
                    self._html(render.home_page(panel.status(), runs, panel.jobs.current, message))
                elif url.path == "/job":
                    self._html(render.job_page(panel.jobs.current))
                elif url.path == "/labels":
                    self._labels_page(query.get("ok", [""])[0], query.get("error", [""])[0])
                elif url.path == "/help":
                    self._html(render.help_page())
                elif url.path == "/tx":
                    self._transaction(query.get("txid", [""])[0].strip().lower())
                elif match := RUN_PATH.match(url.path):
                    run_id, rest = match["run_id"], match["rest"] or ""
                    if rest.startswith("/files/"):
                        self._file(run_file(output_dir, run_id, rest.removeprefix("/files/")))
                    elif rest in ("", "/"):
                        self._html(render.run_page(load_run(output_dir, run_id), panel.reviewer))
                    else:
                        self._not_found()
                else:
                    self._not_found()
            except RunNotFoundError as exc:
                self._html(render.error_page(str(exc)), HTTPStatus.NOT_FOUND)

        def _labels_page(self, message: str, error: str) -> None:
            today = date.today().isoformat()
            try:
                labels = read_labels(panel.config.labels_path)
            except LabelError as exc:
                labels, error = [], f"The labels file has errors: {exc}"
            self._html(render.labels_page(labels, today, message, error))

        def _transaction(self, txid: str) -> None:
            if not render.TXID.match(txid):
                self._html(render.tx_page(txid, None, "Not a valid transaction id."))
                return
            try:
                screener = Screener(
                    load_ofac_list(panel.config.ofac_local_path),
                    read_labels(panel.config.labels_path),
                )
                with panel.services() as services:
                    report = check_transaction(txid, panel.config, services, screener)
            except (OfacError, LabelError, DataSourceError, BlockRangeError) as exc:
                self._html(render.tx_page(txid, None, str(exc)))
                return
            self._html(render.tx_page(txid, report))

        # --- POST ---------------------------------------------------------------------

        def do_POST(self) -> None:  # noqa: N802 - stdlib name
            path = urlparse(self.path).path
            form = self._form()
            try:
                if path == "/run/addresses":
                    panel.jobs.analyse_addresses(form.get("addresses", ""))
                    self._redirect("/job")
                elif path == "/run/blocks":
                    start = int(form["start"])
                    end = int(form["end"]) if form.get("end") else start
                    panel.jobs.scan_blocks(start, end)
                    self._redirect("/job")
                elif path == "/update/ofac":
                    panel.jobs.update_ofac()
                    self._redirect("/job")
                elif path == "/update/fx":
                    panel.jobs.update_fx()
                    self._redirect("/job")
                elif path in ("/labels/add", "/labels/import"):
                    adding_one = path == "/labels/add"
                    text = single_label_csv(form) if adding_one else form.get("csv", "")
                    try:
                        result = panel.import_labels_text(text)
                    except LabelError as exc:
                        error = str(exc).replace("line 2: ", "") if adding_one else str(exc)
                        self._redirect("/labels?error=" + quote(error))
                        return
                    self._redirect(
                        "/labels?ok="
                        + quote(
                            f"{result.added} label(s) added, {result.duplicates} already present. "
                            f"{result.total} labels in total."
                        )
                    )
                elif (match := RUN_PATH.match(path)) and match["rest"] == "/review":
                    run_id = match["run_id"]
                    panel.reviewer = form.get("reviewer", "")
                    save_review(
                        panel.config.output_dir,
                        run_id,
                        form.get("alert_id", ""),
                        form.get("decision", "open"),
                        form.get("note", ""),
                        panel.reviewer,
                    )
                    self._redirect(f"/runs/{run_id}#{quote(form.get('alert_id', ''))}")
                else:
                    self._not_found()
            except (KeyError, ValueError):
                self._redirect("/?error=" + quote("Please fill in the form correctly."))
            except RuntimeError as exc:  # another task is running
                self._redirect("/?error=" + quote(str(exc)))
            except RunNotFoundError as exc:
                self._html(render.error_page(str(exc)), HTTPStatus.NOT_FOUND)

        # --- responses ----------------------------------------------------------------

        def _form(self) -> dict[str, str]:
            length = min(int(self.headers.get("Content-Length", 0)), MAX_FORM_BYTES)
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            return {key: values[0] for key, values in parse_qs(body).items()}

        def _html(self, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _file(self, path: Any) -> None:
            data = path.read_bytes()
            content_type = {
                ".csv": "text/csv",
                ".json": "application/json",
            }.get(path.suffix, "text/plain")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _redirect(self, location: str) -> None:
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", location)
            self.end_headers()

        def _not_found(self) -> None:
            self._html(render.error_page("Page not found."), HTTPStatus.NOT_FOUND)

    return Handler


class LocalServer(ThreadingHTTPServer):
    """ThreadingHTTPServer without the reverse-DNS lookup of the host name.

    The standard server looks up the machine's fully qualified name at startup, which
    can take half a minute on macOS; a localhost-only panel does not need it.
    """

    daemon_threads = True

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = str(host), int(port)


def create_server(
    config: AppConfig, port: int, transport: httpx.BaseTransport | None = None
) -> LocalServer:
    """Build the server bound to localhost (``port`` 0 picks a free port)."""
    panel = ControlPanel(config, transport)
    return LocalServer(("127.0.0.1", port), make_handler(panel))
