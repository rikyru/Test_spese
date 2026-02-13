# Expense Tracker - Project Context & Architecture

**Last Updated:** 2026-02-13
**Tech Stack:** Python, Streamlit, DuckDB, Pandas, Plotly.

## 🎯 Overview
This is a personal finance dashboard designed to track expenses, income,/budget, and recurring payments. It features advanced import capabilities (PDF bills, Bank Screenshots via OCR) and "Smart Rules" for auto-categorization.

## 🏗️ Architecture

```mermaid
graph TD
    User((User))
    
    subgraph UI [Streamlit Frontend]
        App[app.py - Main Entry]
        Dash[ui/dashboard.py]
        Imp[ui/importer.py]
        Sett[ui/settings.py]
        Rec[ui/recurring.py]
    end
    
    subgraph Core [Logic Layer]
        DM[DataManager]
        RE[RulesEngine]
        OCR[OCREngine]
        PDF[PDFParser]
    end
    
    subgraph Data [Persistence]
        DB[(DuckDB - expenses.ddb)]
        Config[config.yaml]
        Pending[pending_transactions.json]
    end

    User --> App
    App --> Dash
    App --> Imp
    App --> Sett
    
    Imp --> OCR
    Imp --> PDF
    Imp --> Pending : "Save Drafts"
    
    OCR --> Pending
    
    DM --> DB
    DM --> RE
    
    Imp --> DM : "Commit Tx"
    RE --> DB : "Learn Patterns"
```

## 🧩 Key Modules

### 1. Data Management (`src/data_manager.py`)
*   **Role**: The "Brain" of the database. Handles all SQL queries to DuckDB.
*   **Key Methods**: `_process_and_insert` (normalizes and saves data), `get_monthly_summary`, `add_recurring`.
*   **Database**: Uses `duckdb` (local file `expenses.ddb`).
*   **Schema**: 
    *   `transactions`: Main table (date, amount, category, account, etc.).
    *   `recurring_expenses`: Templates for fixed costs.

### 2. Smart Import (`src/ui/importer.py`)
*   **Features**:
    *   **CSV/ZIP**: Bulk import from bank exports.
    *   **PDF**: Regex parsing for utility bills (Enel, A2A, etc.).
    *   **Screenshot (New!)**: Uses `easyocr` to read transactions from images.
*   **Review Flow**: Transactions extracted from "messy" sources (Screenshots/Chats) go to a **Pending Queue** (`pending_transactions.json`). The user reviews them in a wizard UI before saving.

### 3. Logic Engines
*   **`src/rules_engine.py`**: Auto-categorizes transactions based on keywords and historical data.
*   **`src/ocr_engine.py`**: State-machine based text extractor.
    *   *Strategy*: Lazy loads `easyocr` (heavy lib) only when needed.
    *   *Logic*: Pairs "Description" lines with their subsequent "Amount" lines, handling clean-up and sign detection.

## 🔄 workflows

### Screenshot Import Flow
1.  **Upload**: User uploads image in `importer.py`.
2.  **OCR**: `OCREngine` scans text, identifying Dates, Descriptions, and Amounts.
3.  **Draft**: Valid pairs are saved to `pending_transactions.json`.
4.  **Review**: UI shows "🧐 Review Pending Utils". User confirms/edits each item.
5.  **Commit**: Confirmed item is inserted into `transactions` table via `DataManager`.

## 🚀 Quick Start
```bash
# Run the app
streamlit run app.py

# Install dependencies
pip install -r requirements.txt
```
