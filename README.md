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
