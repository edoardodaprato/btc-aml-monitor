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

## 5. Analisi di un indirizzo

```bash
btc-aml analyze <indirizzo>
```

Lo strumento scarica lo storico dell'indirizzo (fino a `max_tx_per_address` transazioni),
converte ogni importo in euro al prezzo del giorno, esegue tutte le regole attive e
mostra gli alert con spiegazione e riferimento normativo. La seconda analisi dello stesso
indirizzo usa la cache ed è quasi istantanea.

Se lo storico supera il limite, l'output lo segnala con **TRUNCATED**: le transazioni più
vecchie non sono state analizzate.

### Analisi di una lista di indirizzi (modalità indirizzi)

```bash
btc-aml scan-addresses examples/demo_addresses.txt
```

Il file contiene un indirizzo per riga. Le righe vuote e quelle che iniziano con `#`
vengono ignorate, quindi puoi annotare il file. Le righe non valide vengono segnalate e
saltate senza interrompere l'analisi.

Ogni esecuzione crea una cartella `output/<data-ora>/` con:

| File | Contenuto |
|---|---|
| `address_scores.csv` | Un indirizzo per riga: punteggio, fascia, regole attivate, spiegazione del punteggio |
| `alerts.csv` | Un alert per riga: regola, gravità, contributo al punteggio, transazioni di evidenza, importi, spiegazione, riferimento normativo |
| `transactions.csv` | Tutte le transazioni analizzate, con importo netto, valore in EUR e data del prezzo usato |
| `audit_log.json` | Traccia di audit: data, versione dello strumento, impronta del file di input, versione e parametri delle regole, versione della lista OFAC, fonti dati usate, indirizzi saltati |
| `run.log` | Log tecnico dell'esecuzione |

**Come si calcola il punteggio.** Ogni regola attivata aggiunge il suo peso, una volta
sola anche se genera più alert. Il totale ha un tetto a 100. Fasce: Low 0-24,
Medium 25-49, High 50-74, Severe 75-100. L'esposizione diretta a sanzioni (R01) porta
sempre in Severe. La colonna `score_explanation` mostra il contributo di ogni regola.

**Prezzi in EUR.** Il prezzo storico arriva da mempool.space: orario per le date recenti,
settimanale per quelle più vecchie (fino a 7 giorni prima della transazione), assente
prima di luglio 2010. Per alcuni giorni mempool.space ha il prezzo in dollari ma non in
euro: se hai scaricato i cambi ufficiali BCE con `btc-aml update-fx`, lo strumento converte
il prezzo in dollari al cambio di riferimento BCE di quel giorno. La colonna
`btc_eur_price_source` indica sempre quale fonte è stata usata. Se nessun prezzo è
disponibile, la cella EUR resta vuota.

## 6. Le regole, in parole semplici

| ID | Regola | Cosa significa | Perché è una red flag |
|---|---|---|---|
| R01 | Esposizione diretta a sanzioni | L'indirizzo è nella lista OFAC, o ha scambiato fondi direttamente con un indirizzo che lo è | Possibile violazione di sanzioni: porta sempre in fascia Severe |
| R02 | Esposizione indiretta a sanzioni | Fondi sanzionati a 2-3 passaggi di distanza | Le sanzioni si aggirano con intermediari; il peso si riduce a ogni passaggio |
| R03 | Categorie ad alto rischio | Transazioni dirette con indirizzi etichettati come mixer, darknet market, ransomware, scam | Origine dei fondi illecita o opaca |
| R04 | CoinJoin | Partecipazione a transazioni che mescolano le monete di più utenti | Interrompe deliberatamente la tracciabilità |
| R05 | Peel chain | Catena di transazioni che "sbucciano" piccoli importi e passano il resto avanti | Tipico dell'incasso a rate di fondi rubati |
| R06 | Structuring | Più importi appena sotto 1.000 € o 10.000 € in poche ore | Frazionamento per evitare i controlli (Travel Rule, soglie interne) |
| R07 | Pass-through | Fondi ricevuti e rispediti entro 24 ore, saldo che torna a zero | Conto di transito, comportamento da "money mule" |
| R08 | Fan-in | Molti mittenti diversi in poco tempo | Raccolta di proventi (vittime di truffe, riscatti) |
| R09 | Fan-out | Molti destinatari diversi in poco tempo | Dispersione dei fondi (layering) |
| R10 | Velocità anomala | Troppe transazioni in un giorno | Movimentazione automatizzata |
| R11 | Riattivazione | Indirizzo fermo da oltre un anno che muove importi rilevanti | Possibile incasso di proventi di vecchi reati |
| R12 | Indirizzo nuovo, volumi alti | Grandi importi nelle prime transazioni | Indirizzo "usa e getta" |
| R13 | Importi tondi | Più trasferimenti di esattamente 0,1 o 1 BTC | Accordi OTC o pagamenti predefiniti |
| R14 | Importo elevato | Singola transazione sopra 100.000 € | Rischio intrinseco più alto, richiede verifica dell'origine dei fondi |
| R15 | Dust | Micro-importi da molte fonti | Attacco di tracciamento: l'indirizzo è osservato |
| R16 | Consolidamento | Molti piccoli input riuniti in un'unica transazione | Aggregazione di proventi di piccoli illeciti |
| R17 | Address hopping | Fondi spostati rapidamente su indirizzi nuovi usati una volta | Layering: aumenta la distanza dall'origine senza motivo economico |
| R18 | Consolidamento post-CoinJoin | Più output di CoinJoin riuniti insieme | Raccolta dei fondi "lavati" prima del deposito su exchange |
| R19 | Co-spending con indirizzo segnalato | L'indirizzo firma una transazione insieme a un indirizzo sanzionato o ad alto rischio | Probabilmente appartengono alla stessa entità |
| R20 | Round-trip | I fondi tornano all'origine dopo alcuni passaggi | Flussi circolari: storico artificiale o "ripulitura" |
| R21 | Commissione anomala | Commissione molto sopra la mediana del blocco | Urgenza di spostare i fondi (per esempio dopo un furto) |

**Come leggere gli alert.** Un alert è un indicatore, non una prova. Molte regole
(fan-in, fan-out, consolidamento) scattano anche per servizi legittimi come gli
exchange: ogni alert va letto nel contesto del cliente e dell'indirizzo.

**Importi in euro.** Quando il prezzo storico non è disponibile, le regole basate su
soglie in euro usano la soglia equivalente in BTC e lo scrivono nella spiegazione.
Lo structuring (R06) viene invece valutato solo sulle transazioni con prezzo noto,
perché le sue soglie hanno senso solo in euro.

## 7. Analisi multi-hop, cluster e resto

**Esposizione multi-hop.** Lo strumento segue i fondi oltre le controparti dirette, in
entrambe le direzioni: da dove venivano i soldi ricevuti (origine dei fondi) e dove sono
andati quelli inviati (destinazione). L'importo è attribuito **pro rata**: se una
controparte ha ricevuto il 25% delle sue entrate da un indirizzo sanzionato prima di
pagarci, il 25% di quanto ci ha pagato è considerato esposto. Conta solo ciò che è
avvenuto **prima** (per l'origine) o **dopo** (per la destinazione).

Il peso nel punteggio si riduce con la distanza (`hop_decay`: 100% al primo passaggio,
50% al secondo, 25% al terzo). Per non generare migliaia di chiamate, l'espansione ha dei
limiti: numero di passaggi, indirizzi per passaggio, transazioni per indirizzo, tempo
massimo. Se un limite interviene, il report lo dice (`exposure_complete = False` e
`exposure_notes`).

**Nodi ad alto grado.** Gli indirizzi con moltissime transazioni (oltre
`high_degree_threshold`, di solito exchange e servizi) non vengono espansi: attribuire pro
rata attraverso il portafoglio comune di un exchange non avrebbe senso. Sono elencati in
`high_degree_counterparties`.

**Cluster.** Gli indirizzi che firmano insieme una transazione appartengono di norma allo
stesso portafoglio (euristica *common-input-ownership*); anche il resto (change) torna al
mittente. Lo strumento raggruppa così gli indirizzi della stessa entità probabile,
escludendo i CoinJoin. **Un cluster di migliaia di indirizzi** indica tipicamente un
servizio custodial (per esempio indirizzi di deposito di un exchange raccolti insieme).

**Rilevamento del resto.** Tre euristiche, in ordine di affidabilità: riuso
dell'indirizzo di input, stesso tipo di script degli input, importo non tondo quando il
pagamento è tondo. Se il caso è ambiguo, nessun output viene considerato resto.

## 8. Comandi disponibili

| Comando | Cosa fa |
|---|---|
| `btc-aml show-config` | Controlla e mostra la configurazione |
| `btc-aml fetch-tx <txid>` | Scarica una transazione e ne mostra il valore in EUR |
| `btc-aml update-ofac` | Scarica la lista OFAC aggiornata |
| `btc-aml update-fx` | Scarica i cambi di riferimento BCE EUR/USD |
| `btc-aml import-labels <file.csv>` | Importa etichette da un CSV |
| `btc-aml screen <indirizzo> ...` | Controlla uno o più indirizzi contro OFAC ed etichette |
| `btc-aml analyze <indirizzo>` | Analizza un indirizzo con tutte le regole |
| `btc-aml cache-stats` | Mostra quanti dati sono salvati nella cache locale |
