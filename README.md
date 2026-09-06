# 💰 Finance Dashboard

Un'applicazione locale per la gestione delle finanze personali, costruita con Python, Streamlit e DuckDB.

## 🚀 Installazione su nuovo PC

1.  **Installa Python** (versione 3.10 o superiore).
2.  **Copia questa cartella** (`Test_spese`) nel nuovo computer.
3.  Apri un terminale nella cartella e crea un ambiente virtuale (opzionale ma consigliato):
    ```bash
    python -m venv .venv
    ```
4.  Attiva l'ambiente virtuale:
    *   Windows: `.venv\Scripts\activate`
    *   Mac/Linux: `source .venv/bin/activate`
5.  Installa le dipendenze:
    ```bash
    pip install -r requirements.txt
    ```

## ▶️ Avvio

Esegui il comando:
```bash
python -m streamlit run app.py
```

## 📦 Migrazione (Spostare tutto)

Per spostare l'intero progetto mantenendo dati e cronologia:

1.  **Chiudi l'applicazione** (assicurati che il terminale sia chiuso).
2.  **Copia l'intera cartella** `Test_spese`. Contiene:
    *   `finance.duckdb`: Il database con tutte le tue transazioni.
    *   `rules.yaml`: Le tue regole di categorizzazione e icone.
    *   Tutto il codice sorgente.
3.  (Opzionale) **Chat History**: Se usi lo stesso account sul nuovo PC, la chat potrebbe sincronizzarsi. Se vuoi una copia locale di sicurezza della "memoria" dell'assistente per questa conversazione, copia la cartella:
    *   `C:\Users\ruggi\.gemini\antigravity\brain\9081565f-925f-4235-80c9-592ef501cff0`

## 🛠 Funzionalità Principali

*   **Import**: Carica file ZIP contenenti CSV delle tue banche.
*   **Dashboard**: Visualizza trend, liquidità per portafoglio e grafici.
*   **Settings**: Gestisci categorie, rinomina portafogli, cambia icone, e imposta spese ricorrenti.
*   **Recurring**: Genera automaticamente spese fisse (es. Mutuo).
*   **Backup**: Scarica uno ZIP con tutti i tuoi dati in formato CSV.

## 📱 Pagina rapida sul telefono (`/quick`)

Una singola pagina, servita da `finance_api`, pensata per l'uso da telefono:
totali del mese in alto e inserimento in due tap. Per il dettaglio si apre il
dashboard completo (c'è il link in fondo).

### Installazione sulla home di Android
1.  Apri `https://<tuo-dominio>/quick` in Chrome.
2.  Menu ⋮ → **Aggiungi a schermata Home**.
3.  Si apre a schermo intero, senza barra del browser, con icona propria.

Tenendo premuta l'icona compare anche la scorciatoia **Nuova spesa**, che apre
direttamente il modulo (equivale a `/quick#new`).

### Come funziona l'inserimento
*   I riquadri sono le combinazioni **categoria + tag** che usi di più *di recente*
    (stesso ranking dei "Rapidi" nella sidebar: peso dimezzato ogni 30 giorni),
    con l'importo tipico già precompilato. Un tocco apre il modulo pieno, uno
    conferma.
*   Data = oggi, conto = l'ultimo che hai usato, categoria/necessità/tag mancanti
    li completano le regole, esattamente come nell'inserimento manuale.
*   Senza rete la spesa resta salvata nel telefono e parte da sola al ritorno
    online (o alla riapertura della pagina).

### Perché passa da una coda e non scrive subito
Il dashboard Streamlit tiene una connessione **read-write permanente** su DuckDB,
che non ammette un secondo processo in scrittura. Quindi l'API non tocca il
database: accoda in `finance_data/inbox/inbox.jsonl`, e il dashboard travasa in DB
all'avvio o col pulsante **📱 Sincronizza spese dal telefono** nella sidebar.

Conseguenza pratica: la spesa compare **subito nei totali della pagina rapida**
(che somma la coda), e nel dashboard alla prima apertura successiva. L'id è
generato dal telefono, quindi doppi invii o un travaso interrotto non creano
duplicati; le righe già importate restano in `inbox_archive.jsonl`.
