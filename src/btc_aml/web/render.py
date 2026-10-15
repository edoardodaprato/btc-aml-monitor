"""HTML pages of the control panel. Every value coming from data is escaped."""

from __future__ import annotations

import json
import re
from html import escape
from typing import Any

from btc_aml.block_scan import BlockReport
from btc_aml.data_sources.labels import CATEGORIES, COLUMNS, Label, is_valid_btc_address
from btc_aml.rules.base import fmt_time
from btc_aml.web.jobs import Job
from btc_aml.web.runs import DECISIONS, Run

EXPLORER = "https://mempool.space"
TXID = re.compile(r"^[0-9a-f]{64}$")
MAX_EVIDENCE_SHOWN = 5

CSS = """
:root{--bg:#f7f8fa;--surface:#fff;--surface-2:#eef1f5;--text:#15191f;--muted:#5a6472;
--border:#dde2e9;--accent:#c76a00;--accent-soft:#fff1df;--severe:#b42318;--high:#c4320a;
--medium:#b54708;--low:#4b5563;--ok:#067647;--info:#1d4ed8}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--surface:#151b23;--surface-2:#1c2430;
--text:#e6edf3;--muted:#9aa5b4;--border:#2a3441;--accent:#f59e0b;--accent-soft:#2a1f0d;
--severe:#f97066;--high:#fb8a5c;--medium:#fdb022;--low:#a5b0be;--ok:#47cd89;--info:#7aa2f7}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}
a{color:var(--accent)}code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.88em}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px}
header{border-bottom:1px solid var(--border);background:var(--surface)}
header .wrap{display:flex;align-items:center;gap:20px;height:54px}
header .brand{font-weight:700;color:var(--text);text-decoration:none}
header .brand span{color:var(--accent)}
header nav a{color:var(--muted);text-decoration:none;margin-right:16px;font-size:14px}
main{padding:24px 0 64px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:19px;margin:28px 0 12px}h3{font-size:16px;margin:0 0 8px}
.muted{color:var(--muted)}.small{font-size:13px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.grid-2{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:18px}
.banner{border-radius:10px;padding:12px 16px;margin:0 0 18px;border:1px solid var(--border);
background:var(--accent-soft)}
.banner.error{border-color:var(--severe);color:var(--severe);background:var(--surface)}
.banner.ok{border-color:var(--ok);color:var(--ok);background:var(--surface)}
textarea,input,select{width:100%;font:inherit;padding:8px 10px;border:1px solid var(--border);
border-radius:8px;background:var(--bg);color:var(--text)}
textarea{min-height:120px;font-family:ui-monospace,Menlo,monospace;font-size:13px}
label{display:block;font-size:13px;color:var(--muted);margin:10px 0 4px}
button,.btn{display:inline-block;margin-top:12px;padding:9px 16px;border-radius:8px;border:0;
background:var(--accent);color:#111;font-weight:600;font:inherit;cursor:pointer;text-decoration:none}
button.secondary{background:var(--surface-2);color:var(--text);border:1px solid var(--border)}
button:disabled{opacity:.5;cursor:not-allowed}
.table-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:10px;background:var(--surface)}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--border);vertical-align:top}
th{background:var(--surface-2);white-space:nowrap}tr:last-child td{border-bottom:0}
.tag{display:inline-block;font-size:12px;font-weight:600;padding:0 8px;border-radius:999px;
border:1px solid currentColor;white-space:nowrap}
.sev-severe,.band-Severe{color:var(--severe)}.sev-high,.band-High{color:var(--high)}
.sev-medium,.band-Medium{color:var(--medium)}.sev-low,.band-Low{color:var(--low)}
.dec-escalate{color:var(--severe)}.dec-false_positive,.dec-no_action{color:var(--ok)}
.dec-open{color:var(--muted)}
.alert{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;
margin:10px 0}
.alert .meta{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:6px}
.review{display:grid;grid-template-columns:220px 1fr 160px auto;gap:8px;align-items:end;
margin-top:10px;padding-top:10px;border-top:1px dashed var(--border)}
.review label{margin:0}.review select,.review input{margin-top:4px}.review button{margin:0}
pre.log{background:#0f1720;color:#e6edf3;border-radius:10px;padding:14px;font-size:13px;
max-height:420px;overflow:auto;white-space:pre-wrap}
details>summary{cursor:pointer;color:var(--accent);margin:6px 0}
dl.facts{display:grid;grid-template-columns:220px 1fr;gap:6px 16px;margin:0}
dl.facts dt{color:var(--muted)}dl.facts dd{margin:0;word-break:break-word}
.help li{margin-bottom:6px}
.inline-form{display:inline}.inline-form button{margin:0 0 0 6px;padding:1px 10px;font-size:12px;white-space:nowrap}
@media(max-width:860px){.grid,.grid-2{grid-template-columns:1fr}.review{grid-template-columns:1fr}
dl.facts{grid-template-columns:1fr}}
"""


def page(title: str, body: str, refresh_seconds: int | None = None) -> str:
    refresh = f'<meta http-equiv="refresh" content="{refresh_seconds}">' if refresh_seconds else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">{refresh}
<title>{escape(title)} · btc-aml-monitor</title><style>{CSS}</style></head><body>
<header><div class="wrap"><a class="brand" href="/">btc-aml<span>-monitor</span></a>
<nav><a href="/">Home</a><a href="/#runs">Past runs</a><a href="/labels">Labels</a><a href="/help">How to use</a></nav>
</div></header><main><div class="wrap">{body}</div></main></body></html>"""


# --- home ---------------------------------------------------------------------------------


def home_page(status: dict[str, Any], runs: list[Run], job: Job | None, message: str = "") -> str:
    busy = job is not None and job.status == "running"
    disabled = " disabled" if busy else ""
    parts = []
    if busy:
        parts.append(
            f'<div class="banner">⏳ <b>{escape(job.description)}</b> is running. '
            f'<a href="/job">Follow its progress</a>.</div>'
        )
    if message:
        parts.append(f'<div class="banner error">{escape(message)}</div>')
    if status["ofac"] is None:
        parts.append(
            '<div class="banner error">The OFAC sanctions list is not downloaded yet. '
            "Use <b>Update OFAC list</b> below before running an analysis.</div>"
        )

    parts.append(f"""
<h1>Control panel</h1>
<p class="muted">Run an analysis, then open it from <a href="#runs">Past runs</a> to read the
results, check the evidence on a block explorer and record your review of each alert.
New here? Read <a href="/help">How to use</a>.</p>
<div class="grid">
  <form class="card" method="post" action="/run/addresses">
    <h3>1 · Analyse addresses</h3>
    <p class="muted small">Full history, all 21 rules, multi-hop exposure and a 0-100 risk score
    per address. A few minutes per address the first time.</p>
    <label for="addresses">Bitcoin addresses, one per line (lines starting with # are ignored)</label>
    <textarea id="addresses" name="addresses" required placeholder="bc1q...&#10;1A1zP1..."></textarea>
    <button{disabled}>Start analysis</button>
  </form>
  <form class="card" method="post" action="/run/blocks">
    <h3>2 · Scan blocks</h3>
    <p class="muted small">Every transaction of up to {status["max_blocks"]} blocks, checked with
    the single-transaction rules. About a minute per block the first time.</p>
    <label for="start">First block height</label>
    <input id="start" name="start" type="number" min="0" required placeholder="e.g. 733459">
    <label for="end">Last block height (optional, inclusive)</label>
    <input id="end" name="end" type="number" min="0" placeholder="same as first">
    <p class="muted small">Latest block known: {escape(str(status["tip"] or "unknown"))}</p>
    <button{disabled}>Start scan</button>
  </form>
  <form class="card" method="get" action="/tx">
    <h3>3 · Check one transaction</h3>
    <p class="muted small">Quick check of a confirmed transaction: sanctioned or labelled
    addresses, CoinJoin, large amounts, fees. Not saved; for a recorded analysis use 1.</p>
    <label for="txid">Transaction id (txid)</label>
    <input id="txid" name="txid" required pattern="[0-9a-fA-F]{{64}}" placeholder="64 hex characters">
    <button>Check</button>
  </form>
</div>
<h2>Reference data</h2>
<div class="grid">
  <form class="card" method="post" action="/update/ofac">
    <h3>OFAC sanctions list</h3>
    {_ofac_status(status["ofac"])}
    <button class="secondary"{disabled}>Update OFAC list</button>
  </form>
  <form class="card" method="post" action="/update/fx">
    <h3>ECB EUR/USD rates</h3>
    <p class="small">{escape(status["fx"] or "Not downloaded: EUR gaps in prices will not be filled.")}</p>
    <button class="secondary"{disabled}>Update ECB rates</button>
  </form>
  <div class="card">
    <h3>Your labels and settings</h3>
    <p class="small">{status["labels"]} labelled addresses ({escape(status["labels_path"])}).
    <a href="/labels">View and add labels</a>.</p>
    <p class="small">Rules v{escape(status["rules_version"])}, configuration hash
    <code>{escape(status["config_hash"])}</code>. Thresholds are in <code>config/rules.yaml</code>.</p>
  </div>
</div>
<h2 id="runs">Past runs</h2>
{_runs_table(runs)}
""")
    return page("Control panel", "".join(parts))


def _ofac_status(ofac: dict[str, Any] | None) -> str:
    if ofac is None:
        return '<p class="small sev-severe">Not downloaded.</p>'
    return (
        f'<p class="small">Published <b>{escape(ofac["publish_date"])}</b>, downloaded '
        f"{escape(ofac['downloaded_at'][:10])}: {ofac['addresses']} Bitcoin addresses. "
        "OFAC updates the list often: refresh it before an important analysis.</p>"
    )


def _runs_table(runs: list[Run]) -> str:
    if not runs:
        return '<p class="muted">No runs yet.</p>'
    rows = []
    for run in runs:
        results = run.audit.get("results", {})
        if run.mode == "blocks":
            blocks = results.get("blocks_scanned", [])
            what = f"Blocks {_block_range(blocks)} · {results.get('transactions_scanned', 0)} tx"
        else:
            what = f"{results.get('addresses_analysed', 0)} address(es)"
        total = len(run.alerts)
        progress = f"{run.reviewed_count} / {total}" if total else "no alerts"
        rows.append(
            f'<tr><td><a href="/runs/{run.run_id}">{escape(_run_time(run.run_id))}</a></td>'
            f"<td>{escape(_mode_name(run.mode))}</td><td>{escape(what)}</td>"
            f"<td>{total}</td><td>{escape(progress)}</td></tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr><th>Run (UTC)</th><th>Mode</th>'
        "<th>Scope</th><th>Alerts</th><th>Reviewed</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


# --- job progress ------------------------------------------------------------------------


def job_page(job: Job | None) -> str:
    if job is None:
        return page("No task", '<p>No task has been started. <a href="/">Back</a>.</p>')
    log = escape("\n".join(job.log) or "Starting...")
    if job.status == "running":
        body = (
            f"<h1>{escape(job.description)}</h1><p class='muted'>Running since "
            f"{job.started_at:%H:%M:%S} UTC. This page refreshes every 3 seconds; you can "
            "leave it and come back.</p>"
            f'<pre class="log">{log}</pre>'
        )
        return page(job.description, body, refresh_seconds=3)
    if job.status == "failed":
        body = (
            f"<h1>{escape(job.description)}: failed</h1>"
            f'<div class="banner error">{escape(job.error or "")}</div>'
            f'<pre class="log">{log}</pre><a class="btn" href="/">Back to the control panel</a>'
        )
        return page(job.description, body)
    link = (
        f'<a class="btn" href="/runs/{job.run_id}">Open the results</a>'
        if job.run_id
        else '<a class="btn" href="/">Back to the control panel</a>'
    )
    body = (
        f"<h1>{escape(job.description)}: done</h1>"
        f'<div class="banner ok">Finished.</div><pre class="log">{log}</pre>{link}'
    )
    return page(job.description, body)


# --- one run -----------------------------------------------------------------------------


def run_page(run: Run, reviewer: str) -> str:
    audit = run.audit
    total = len(run.alerts)
    downloads = " · ".join(
        f'<a href="/runs/{run.run_id}/files/{name}">{name}</a>'
        for name in sorted(audit.get("report_files", {}).values())
        + ["audit_log.json", "run.log"]
        + (["review.csv"] if (run.folder / "review.csv").is_file() else [])
    )
    header = f"""
<h1>{escape(_mode_name(run.mode))} · {escape(_run_time(run.run_id))} UTC</h1>
<p class="muted">Run <code>{escape(run.run_id)}</code> · tool v{escape(str(audit.get("tool_version")))}
· {total} alerts · <b>{run.reviewed_count} reviewed</b> ·
<a href="#audit">Audit trail</a></p>
<p class="small">Files: {downloads}</p>"""
    if run.mode == "blocks":
        content = _block_results(run, reviewer)
    else:
        content = _address_results(run, reviewer)
    return page(f"Run {run.run_id}", header + content + _audit_section(run))


def _address_results(run: Run, reviewer: str) -> str:
    scores = run.tables.get("address_scores", [])
    alerts_by_address: dict[str, list[dict[str, str]]] = {}
    for alert in run.alerts:
        alerts_by_address.setdefault(alert["address"], []).append(alert)
    txs_by_address: dict[str, list[dict[str, str]]] = {}
    for tx in run.tables.get("transactions", []):
        txs_by_address.setdefault(tx["address"], []).append(tx)

    rows = "".join(
        f'<tr><td><a href="#a-{escape(s["address"])}" class="mono">{escape(s["address"])}</a></td>'
        f"<td><b>{escape(s['risk_score'])}</b></td>"
        f'<td><span class="tag band-{escape(s["risk_band"])}">{escape(s["risk_band"])}</span></td>'
        f"<td>{escape(s['tx_count'])}{' (truncated)' if s['history_truncated'] == 'True' else ''}</td>"
        f"<td>{len(alerts_by_address.get(s['address'], []))}</td></tr>"
        for s in sorted(scores, key=lambda s: -int(s["risk_score"]))
    )
    parts = [
        "<h2>Results</h2>",
        '<div class="table-wrap"><table><thead><tr><th>Address</th><th>Score</th><th>Band</th>'
        f"<th>Transactions</th><th>Alerts</th></tr></thead><tbody>{rows}</tbody></table></div>",
    ]
    skipped = run.audit.get("results", {}).get("addresses_skipped", {})
    if skipped:
        items = "".join(
            f"<li><code>{escape(k)}</code>: {escape(v)}</li>" for k, v in skipped.items()
        )
        parts.append(f'<div class="banner error">Not analysed:<ul>{items}</ul></div>')

    for s in scores:
        address = s["address"]
        notes = []
        if s["history_truncated"] == "True":
            notes.append("History truncated: only the most recent transactions were analysed.")
        if s.get("exposure_complete") == "False":
            notes.append(f"Exposure search incomplete: {s.get('exposure_notes', '')}")
        if s.get("rules_not_evaluated"):
            notes.append(f"Rules not evaluated (API errors): {s['rules_not_evaluated']}")
        note_html = "".join(f'<p class="small sev-medium">⚠ {escape(n)}</p>' for n in notes)
        parts.append(f"""
<h2 id="a-{escape(address)}"><span class="mono">{escape(address)}</span></h2>
<div class="card">
<p><b>Score {escape(s["risk_score"])}</b>
<span class="tag band-{escape(s["risk_band"])}">{escape(s["risk_band"])}</span> ·
{_address_link(address, "open on block explorer")}</p>
<p class="small"><b>Why:</b> {escape(s["score_explanation"] or "no rule triggered")}</p>
<p class="small muted">Received {escape(s["total_received_btc"])} BTC · sent
{escape(s["total_sent_btc"])} BTC · active {escape(s["first_seen"][:10])} →
{escape(s["last_seen"][:10])} · cluster of {escape(s["cluster_size"])} address(es)</p>
{note_html}
</div>""")
        for alert in alerts_by_address.get(address, []):
            parts.append(_alert_card(run, alert, reviewer, subject=address))
        txs = txs_by_address.get(address, [])
        if txs:
            parts.append(_transactions_table(txs))
    return "".join(parts)


def _block_results(run: Run, reviewer: str) -> str:
    rows = "".join(
        f"<tr><td>{escape(b['block_height'])}</td><td>{escape(b['block_time'][:16])}</td>"
        f"<td>{escape(b['tx_count'])}</td><td>{escape(b['median_fee_rate_sat_vb'])}</td>"
        f"<td>{escape(b['btc_eur_price'])}</td><td>{escape(b['alerts'])}</td></tr>"
        for b in run.tables.get("blocks", [])
    )
    parts = [
        "<h2>Blocks</h2>",
        '<div class="table-wrap"><table><thead><tr><th>Height</th><th>Time (UTC)</th>'
        "<th>Transactions</th><th>Median fee (sat/vB)</th><th>BTC/EUR</th><th>Alerts</th></tr>"
        f"</thead><tbody>{rows}</tbody></table></div>",
        '<p class="small muted">Block scan produces leads, not scores. Large transfers, batch '
        "payouts and consolidations are mostly ordinary exchange and mining-pool activity; "
        "sanctions (R01) and co-spending (R19) alerts come first.</p>",
    ]
    by_rule: dict[str, list[dict[str, str]]] = {}
    for alert in run.alerts:
        by_rule.setdefault(alert["rule_id"], []).append(alert)
    order = {"severe": 0, "high": 1, "medium": 2, "low": 3}
    for rule_id, alerts in sorted(
        by_rule.items(), key=lambda item: (order.get(item[1][0]["severity"], 9), item[0])
    ):
        first = alerts[0]
        is_open = " open" if first["severity"] in ("severe", "high") else ""
        cards = "".join(
            _alert_card(run, a, reviewer, subject=f"block {a['block_height']}") for a in alerts
        )
        parts.append(
            f"<details{is_open}><summary><b>{escape(rule_id)}</b> · {escape(first['rule_name'])} · "
            f'<span class="tag sev-{escape(first["severity"])}">{escape(first["severity"])}</span> · '
            f"{len(alerts)} alert(s)</summary>{cards}</details>"
        )
    return "".join(parts)


def _alert_card(run: Run, alert: dict[str, str], reviewer: str, subject: str) -> str:
    alert_id = alert["alert_id"]
    review = run.decision_of(alert_id)
    decision = review["decision"]
    txids = [t for t in alert["evidence_txids"].split(";") if t]
    shown = ", ".join(_tx_link(t) for t in txids[:MAX_EVIDENCE_SHOWN])
    more = ""
    if len(txids) > MAX_EVIDENCE_SHOWN:
        rest = ", ".join(_tx_link(t) for t in txids[MAX_EVIDENCE_SHOWN:])
        more = (
            f"<details><summary>+{len(txids) - MAX_EVIDENCE_SHOWN} more</summary>{rest}</details>"
        )
    amount = f"{alert['amount_btc']} BTC" + (
        f" ({float(alert['amount_eur']):,.0f} EUR)" if alert.get("amount_eur") else " (EUR n/a)"
    )
    extra = []
    if alert.get("score_contribution"):
        extra.append(f"score +{escape(alert['score_contribution'])}")
    if alert.get("hop_distance") not in (None, "", "0"):
        extra.append(f"hop {escape(alert['hop_distance'])}")
    if alert.get("addresses"):
        extra.append(f"addresses: {escape(alert['addresses'])}")
    options = "".join(
        f'<option value="{key}"{" selected" if key == decision else ""}>{escape(text)}</option>'
        for key, text in DECISIONS.items()
    )
    reviewed = (
        f" · reviewed {escape(review.get('reviewed_at', '')[:16])}"
        f"{' by ' + escape(review['reviewer']) if review.get('reviewer') else ''}"
        if decision != "open"
        else ""
    )
    return f"""
<div class="alert" id="{escape(alert_id)}">
<div class="meta"><span class="tag sev-{escape(alert["severity"])}">{escape(alert["severity"])}</span>
<b>{escape(alert["rule_id"])}</b> {escape(alert["rule_name"])}
<span class="tag dec-{escape(decision)}">{escape(DECISIONS.get(decision, decision))}</span>
<span class="small muted">{escape(alert_id)}{reviewed}</span></div>
<div>{escape(alert["explanation"])}</div>
<div class="small muted">Amount {escape(amount)}{" · " + " · ".join(extra) if extra else ""}</div>
<div class="small muted">Reference: {escape(alert["regulatory_reference"])}</div>
<div class="small">Evidence (verify on the block explorer): {shown}{more}</div>
<form class="review" method="post" action="/runs/{run.run_id}/review">
<input type="hidden" name="alert_id" value="{escape(alert_id)}">
<label>Decision<select name="decision" aria-label="Decision on {escape(subject)}">{options}</select></label>
<label>Note (reasoning, documents checked)
<input name="note" value="{escape(review.get("note", ""))}" maxlength="1000"></label>
<label>Reviewer<input name="reviewer" value="{escape(review.get("reviewer") or reviewer)}"
maxlength="80"></label>
<button>Save</button></form>
</div>"""


def _transactions_table(txs: list[dict[str, str]]) -> str:
    rows = "".join(
        f"<tr><td>{_tx_link(t['txid'])}</td><td>{escape(t['block_time'][:16])}</td>"
        f"<td>{escape(t['block_height'])} {_scan_block_button(t['block_height'])}</td>"
        f"<td>{escape(t['direction'])}</td><td>{escape(t['amount_btc'])}</td>"
        f"<td>{escape(t['amount_eur'])}</td><td class='small'>{escape(t['btc_eur_price_source'])} "
        f"{escape(t['btc_eur_price_date'])}</td><td>{'yes' if t['is_coinjoin'] == 'True' else ''}</td></tr>"
        for t in reversed(txs)
    )
    return (
        f"<details><summary>All {len(txs)} analysed transactions</summary>"
        '<p class="small muted">"Scan block" checks every transaction of the block that contains '
        "this one: useful to see who else was active alongside this address.</p>"
        '<div class="table-wrap"><table><thead><tr><th>Transaction</th><th>Time (UTC)</th>'
        "<th>Block</th><th>Direction</th><th>BTC</th><th>EUR</th><th>Price used</th><th>CoinJoin</th></tr>"
        f"</thead><tbody>{rows}</tbody></table></div></details>"
    )


def _audit_section(run: Run) -> str:
    audit = run.audit
    sanctions = audit.get("sanctions_list", {})
    rules = audit.get("rules", {})
    results = audit.get("results", {})
    facts = {
        "Started / finished (UTC)": f"{audit.get('started_at')} → {audit.get('finished_at')}",
        "Tool version": audit.get("tool_version"),
        "Input": json.dumps(audit.get("input", {})),
        "Rules version / config hash": f"{rules.get('rules_version')} / {rules.get('config_hash')}",
        "OFAC list": f"published {sanctions.get('publish_date')}, "
        f"{sanctions.get('xbt_addresses')} addresses, version {sanctions.get('version')}",
        "ECB rates": audit.get("fx_rates", {}).get("version"),
        "Labels file": json.dumps(audit.get("labels", {})),
        "Data sources used (requests)": json.dumps(audit.get("data_sources_used", {})),
    }
    for key, label in (
        ("addresses_skipped", "Addresses skipped"),
        ("blocks_skipped", "Blocks skipped"),
        ("truncated_histories", "Truncated histories"),
        ("rules_not_evaluated", "Rules not evaluated"),
        ("incomplete_exposure", "Incomplete exposure"),
        ("blocks_without_fee_statistics", "Blocks without fee statistics"),
        ("blocks_without_eur_price", "Blocks without EUR price"),
    ):
        if results.get(key):
            facts[label] = json.dumps(results[key])
    facts_html = "".join(f"<dt>{escape(k)}</dt><dd>{escape(str(v))}</dd>" for k, v in facts.items())
    definitions = rules.get("definitions", {})
    rule_rows = "".join(
        f"<tr><td class='mono'>{escape(rule_id)}</td><td>{'yes' if d.get('enabled') else 'no'}</td>"
        f"<td>{escape(str(d.get('weight')))}</td><td>{escape(str(d.get('severity')))}</td>"
        f"<td class='mono small'>{escape(json.dumps(d.get('params', {})))}</td></tr>"
        for rule_id, d in definitions.items()
    )
    raw = escape(json.dumps(audit, indent=2))
    return f"""
<h2 id="audit">Audit trail</h2>
<div class="card"><dl class="facts">{facts_html}</dl></div>
<details><summary>Rule definitions and thresholds used in this run</summary>
<div class="table-wrap"><table><thead><tr><th>Rule</th><th>On</th><th>Weight</th><th>Severity</th>
<th>Thresholds</th></tr></thead><tbody>{rule_rows}</tbody></table></div></details>
<details><summary>Full audit_log.json</summary><pre class="log">{raw}</pre></details>"""


# --- single transaction ------------------------------------------------------------------


def tx_page(txid: str, report: BlockReport | None, error: str = "") -> str:
    body = [f'<h1>Transaction check</h1><p class="mono small">{escape(txid)}</p>']
    if error:
        body.append(f'<div class="banner error">{escape(error)}</div>')
        return page("Transaction check", "".join(body))
    assert report is not None
    tx = report.txs[0]
    block = report.block
    price = f"{block.price.eur:,.0f} EUR/BTC ({block.price.source})" if block.price else "n/a"
    body.append(f"""
<div class="card"><p>{_tx_link(txid, "open on block explorer")}</p>
<dl class="facts">
<dt>Block</dt><dd>{block.height} · {escape(fmt_time(block.timestamp))} {_scan_block_button(str(block.height))}</dd>
<dt>Inputs / outputs</dt><dd>{len(tx.inputs)} / {len(tx.outputs)}</dd>
<dt>Total output</dt><dd>{tx.total_output_sats / 1e8:.8f} BTC</dd>
<dt>Fee</dt><dd>{tx.fee_sats} sats ({tx.fee_rate:.1f} sat/vB; block median
{f"{block.median_fee_rate:.1f}" if block.median_fee_rate is not None else "n/a"})</dd>
<dt>BTC/EUR on that day</dt><dd>{escape(price)}</dd></dl></div>""")
    if not report.findings:
        body.append('<div class="banner ok">No red flag on this transaction alone.</div>')
    for finding in report.findings:
        addresses = ", ".join(_address_link(a) for a in finding.addresses[:10])
        more = f" (+{len(finding.addresses) - 10} more)" if len(finding.addresses) > 10 else ""
        body.append(f"""
<div class="alert"><div class="meta"><span class="tag sev-{escape(finding.severity)}">
{escape(finding.severity)}</span><b>{escape(finding.rule_id)}</b> {escape(finding.rule_name)}</div>
<div>{escape(finding.explanation)}</div>
<div class="small muted">Addresses: {addresses}{more}</div>
<div class="small muted">Reference: {escape(finding.regulatory_reference)}</div></div>""")
    involved = sorted(tx.input_addresses | tx.output_addresses)
    body.append(
        '<p class="small muted">Only single-transaction rules apply here. To record a full '
        "analysis, paste the addresses below into <b>Analyse addresses</b> on the "
        "control panel:</p>"
        f'<pre class="log">{escape(chr(10).join(involved))}</pre>'
    )
    return page("Transaction check", "".join(body))


# --- help --------------------------------------------------------------------------------


def help_page() -> str:
    body = """
<h1>How to use</h1>
<div class="grid-2">
<div class="card help"><h3>Before the first analysis</h3><ol>
<li><b>Update OFAC list</b> on the control panel. Repeat it regularly (OFAC changes the list often).</li>
<li>Optional: <b>Update ECB rates</b>, to fill days where no EUR price exists.</li>
<li>Optional: add your own labels (mixer, scam...) on the <a href="/labels">Labels</a> page,
one at a time or by pasting a CSV. Each needs a verifiable public source.</li></ol></div>
<div class="card help"><h3>Which analysis?</h3><ul>
<li><b>Analyse addresses</b>: you know the addresses (a customer's deposit address, a
counterparty). Gives a 0-100 score per address with all rules. This is the main mode.</li>
<li><b>Scan blocks</b>: you want to see what happened in a period, without addresses.
Gives leads (sanctioned addresses, CoinJoins...) and a list of addresses to analyse next.</li>
<li><b>Check one transaction</b>: you have a txid in hand and want a quick look.</li></ul></div>
<div class="card help"><h3>Reading the results</h3><ul>
<li><b>Score and band</b>: Low 0-24, Medium 25-49, High 50-74, Severe 75-100. Direct
sanctions exposure is always Severe. "Why" lists every rule's contribution.</li>
<li><b>Each alert</b> says what was found, the amount, the regulatory reference and the
transactions behind it.</li>
<li><b>Warnings</b> (⚠) tell you when a limit was hit: truncated history, incomplete
exposure search, rules that could not run.</li></ul></div>
<div class="card help"><h3>Manual review (four-eyes check)</h3><ol>
<li>Open the evidence links: they show the transactions on mempool.space, a public block
explorer, so you can verify amounts, dates and addresses independently.</li>
<li>Pick a decision: <i>Escalate</i>, <i>False positive</i> or <i>Explained, no action</i>,
and write why (documents checked, customer explanation...).</li>
<li>Decisions are saved in the run folder (<code>review.json</code>, exported as
<code>review.csv</code>) next to the original reports, which are never changed.</li>
<li>The <b>Audit trail</b> section shows exactly which rules, thresholds, sanctions list
version and data sources produced the results.</li></ol></div>
<div class="card help"><h3>Where to find addresses and blocks</h3><ul>
<li>Everything on the Bitcoin blockchain is public. A <b>block explorer</b> such as
<a href="https://mempool.space" target="_blank" rel="noopener">mempool.space</a> lets you search any
address, transaction id or block number (the block <i>height</i>).</li>
<li><b>Start from a known case</b>: sanctions press releases (OFAC), court filings and
Europol or Department of Justice announcements often quote addresses or txids.</li>
<li><b>From address to block</b>: analyse an address, open "All analysed transactions" and
press <i>Scan block</i> next to a transaction to check everything else in that block.</li>
<li>A random block mostly shows ordinary exchange and mining-pool activity: block scan is
most useful when you already know something happened there.</li></ul></div>
<div class="card help"><h3>Typical workflow</h3><ol>
<li>Update the OFAC list.</li>
<li>Analyse the customer's or counterparty's addresses.</li>
<li>Read the score and the reasons; open the alerts with the highest severity first.</li>
<li>Verify each alert on the block explorer; if useful, scan the blocks of key transactions.</li>
<li>Record a decision and a note for every alert; download <code>review.csv</code> for the file.</li></ol></div>
</div>
<p class="small muted">Where files are: every run is a folder <code>output/&lt;run id&gt;/</code>
inside the project folder, with the CSV reports, the audit log and your review. Alerts are
leads to investigate, not conclusions: see the known limitations in the README.</p>"""
    return page("How to use", body)


def labels_page(labels: list[Label], today: str, message: str = "", error: str = "") -> str:
    banner = ""
    if message:
        banner = f'<div class="banner ok">{escape(message)}</div>'
    if error:
        banner = f'<div class="banner error">Nothing was imported. {escape(error)}</div>'
    options = "".join(f'<option value="{c}">{c}</option>' for c in sorted(CATEGORIES))
    rows = "".join(
        f"<tr><td>{_address_link(label.address)}</td><td>{escape(label.category)}</td>"
        f"<td class='small'>{_source_html(label.source)}</td><td>{escape(label.date_added)}</td></tr>"
        for label in sorted(labels, key=lambda label: (label.category, label.address))
    )
    table = (
        '<div class="table-wrap"><table><thead><tr><th>Address</th><th>Category</th>'
        f"<th>Source</th><th>Added</th></tr></thead><tbody>{rows}</tbody></table></div>"
        if labels
        else '<p class="muted">No labels yet.</p>'
    )
    body = f"""
<h1>Address labels</h1>
<p class="muted">Labels attribute an address to a category (exchange, mixer, scam...). Analyses use
them for the high-risk exposure and co-spending rules (R03, R19). <b>Every label must cite a
verifiable public source</b> (court filing, official press release, an exchange's own
proof-of-reserves page): never add an attribution you could not justify to an auditor.
OFAC addresses are handled automatically by the OFAC list and must not be added here.</p>
{banner}
<div class="grid-2">
  <form class="card" method="post" action="/labels/add">
    <h3>Add one label</h3>
    <label for="l-address">Bitcoin address</label>
    <input id="l-address" name="address" required>
    <label for="l-category">Category</label>
    <select id="l-category" name="category">{options}</select>
    <label for="l-source">Source (link or document reference)</label>
    <input id="l-source" name="source" required placeholder="e.g. https://www.justice.gov/... (case no. ...)">
    <label for="l-date">Date added</label>
    <input id="l-date" name="date_added" type="date" value="{escape(today)}" required>
    <button>Add label</button>
  </form>
  <form class="card" method="post" action="/labels/import">
    <h3>Import many labels (CSV)</h3>
    <p class="muted small">Paste a CSV with the header <code>{",".join(COLUMNS)}</code>, for example
    copied from a spreadsheet saved as CSV. Every line is checked; if one line is wrong, nothing is
    imported and the message says which line to fix. Labels already present are skipped.</p>
    <label for="l-csv">CSV content</label>
    <textarea id="l-csv" name="csv" required placeholder="{",".join(COLUMNS)}&#10;bc1q...,scam,https://...,{escape(today)}"></textarea>
    <button>Import</button>
  </form>
</div>
<h2>Current labels ({len(labels)})</h2>
{table}"""
    return page("Labels", body)


def _source_html(source: str) -> str:
    if source.startswith(("https://", "http://")):
        return f'<a href="{escape(source)}" target="_blank" rel="noopener">{escape(source)}</a>'
    return escape(source)


def error_page(message: str) -> str:
    return page("Error", f'<div class="banner error">{escape(message)}</div><a href="/">Back</a>')


# --- small helpers -----------------------------------------------------------------------


def _tx_link(txid: str, text: str | None = None) -> str:
    if not TXID.match(txid):
        return escape(txid)
    label = escape(text) if text else f"<span class='mono'>{txid[:10]}…</span>"
    return f'<a href="{EXPLORER}/tx/{txid}" target="_blank" rel="noopener">{label}</a>'


def _scan_block_button(height: str) -> str:
    """Small form that starts a block scan of ``height`` (posts to the normal scan route)."""
    if not height.isdigit():
        return ""
    return (
        f'<form class="inline-form" method="post" action="/run/blocks">'
        f'<input type="hidden" name="start" value="{height}">'
        f'<button class="secondary" title="Scan every transaction of block {height}">Scan block</button>'
        "</form>"
    )


def _address_link(address: str, text: str | None = None) -> str:
    if not is_valid_btc_address(address):
        return escape(address)
    label = escape(text) if text else f"<span class='mono'>{escape(address)}</span>"
    return f'<a href="{EXPLORER}/address/{address}" target="_blank" rel="noopener">{label}</a>'


def _run_time(run_id: str) -> str:
    return f"{run_id[0:4]}-{run_id[4:6]}-{run_id[6:8]} {run_id[9:11]}:{run_id[11:13]}"


def _mode_name(mode: str) -> str:
    return {"addresses": "Address analysis", "blocks": "Block scan"}.get(mode, mode)


def _block_range(blocks: list[int]) -> str:
    if not blocks:
        return "none"
    return str(blocks[0]) if len(blocks) == 1 else f"{blocks[0]}-{blocks[-1]}"
