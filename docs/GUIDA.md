# Guida a btc-aml-monitor

Guida in italiano per chi parte da zero. Viene aggiornata a ogni fase del progetto.

## 1. Installazione

Servono Python 3.11 o superiore e Git. Dal Terminale:

```bash
git clone https://github.com/edoardodaprato/btc-aml-monitor.git
cd btc-aml-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

| Comando | Cosa fa |
|---|---|
| `git clone ...` | Scarica il progetto da GitHub |
| `python3 -m venv .venv` | Crea un ambiente Python isolato, solo per questo progetto |
| `source .venv/bin/activate` | Attiva l'ambiente: va ripetuto ogni volta che apri un nuovo Terminale |
| `pip install -e ".[dev]"` | Installa lo strumento e le librerie necessarie |

Per verificare che tutto funzioni:

```bash
btc-aml show-config
pytest
```

## 2. Configurazione

Tutte le soglie, i pesi e i limiti stanno in due file di testo, modificabili senza
toccare il codice:

- `config/settings.yaml`: fonti dati, limiti di richieste, profondità dell'analisi
  multi-hop, fasce di rischio.
- `config/rules.yaml`: per ogni regola, attivazione (`enabled`), peso nel punteggio
  (`weight`), gravità (`severity`) e soglie (`params`).

Se un valore non è valido (per esempio un peso di 150 o un buco tra le fasce di
rischio), lo strumento si ferma con un messaggio chiaro invece di produrre punteggi
sbagliati. `btc-aml show-config` mostra la configurazione in uso e il suo **hash**,
cioè l'impronta che finisce nell'audit log di ogni analisi.

## 3. Lista sanzioni OFAC

```bash
btc-aml update-ofac
```

Scarica la lista SDN ufficiale dal sito del Tesoro USA ed estrae gli indirizzi Bitcoin
(tipo "Digital Currency Address - XBT"), con l'entità designata e i programmi
sanzionatori. Salva anche la data di pubblicazione e l'impronta SHA-256 del file:
insieme formano la **versione della lista** registrata in ogni analisi.

Va rieseguito periodicamente (per esempio ogni settimana), perché l'OFAC aggiorna la
lista di frequente.

> Nota: lo stesso indirizzo può essere attribuito a più persone o entità. Lo strumento
> le conserva tutte, perché ogni designazione è rilevante ai fini del reporting.

## 4. Etichette degli indirizzi

Il file `data/labels.csv` contiene le tue attribuzioni: indirizzo → categoria.
Si parte dal modello vuoto `data/labels_template.csv`:

```
address,category,source,date_added
```

| Colonna | Contenuto |
|---|---|
| `address` | Indirizzo Bitcoin |
| `category` | Una tra: `exchange`, `mixer`, `darknet_market`, `ransomware`, `scam`, `gambling`, `sanctioned` |
| `source` | Link o riferimento **verificabile** alla fonte pubblica (obbligatorio) |
| `date_added` | Data di inserimento, formato `AAAA-MM-GG` |

### Procedura di import

1. Prepara un CSV con le stesse quattro colonne, partendo da una copia del modello.
2. Per ogni riga, indica nella colonna `source` il documento pubblico da cui proviene
   l'attribuzione.
3. Importa:

   ```bash
   btc-aml import-labels mio_file.csv
   ```

4. Il file viene controllato riga per riga. Se anche una sola riga è errata (indirizzo
   malformato, categoria sconosciuta, fonte mancante, data sbagliata), **l'import viene
   rifiutato per intero** e il messaggio indica le righe da correggere. Le righe già
   presenti vengono saltate, quindi lo stesso file si può reimportare senza creare doppioni.

### Fonti pubbliche verificabili

Principio guida: **mai inserire un'attribuzione che non si possa documentare** davanti
a un auditor o a un'autorità di vigilanza.

| Fonte | Categorie tipiche | Note |
|---|---|---|
| Atti giudiziari e comunicati del Dipartimento di Giustizia USA (es. atti di confisca) | darknet_market, ransomware, scam, mixer | Spesso riportano gli indirizzi in allegato; citare il numero del procedimento |
| Comunicati di Europol, Eurojust e autorità nazionali | darknet_market, mixer | Operazioni di chiusura di marketplace e mixer |
| Indirizzi di Proof of Reserves pubblicati dagli exchange | exchange | Pubblicati dagli exchange stessi; citare la pagina ufficiale |
| Dataset aperti di ricerca (es. raccolte di indirizzi di pagamento ransomware) | ransomware | Verificare per ogni indirizzo la prova allegata alla segnalazione |

Gli indirizzi OFAC **non** vanno copiati nel file etichette: sono già gestiti
automaticamente da `btc-aml update-ofac`.

## 5. Comandi disponibili

| Comando | Cosa fa |
|---|---|
| `btc-aml show-config` | Controlla e mostra la configurazione |
| `btc-aml fetch-tx <txid>` | Scarica una transazione e ne mostra il valore in EUR |
| `btc-aml update-ofac` | Scarica la lista OFAC aggiornata |
| `btc-aml import-labels <file.csv>` | Importa etichette da un CSV |
| `btc-aml screen <indirizzo> ...` | Controlla uno o più indirizzi contro OFAC ed etichette |
| `btc-aml cache-stats` | Mostra quanti dati sono salvati nella cache locale |
