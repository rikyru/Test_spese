import os
import shutil
import time
import calendar
from datetime import date, datetime
from typing import Optional

import duckdb
import pandas as pd
import numpy as np
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

DB_PATH = os.getenv("DB_PATH", "/app/data/finance.duckdb")
SNAPSHOT_PATH = "/tmp/finance_snapshot.duckdb"
SNAPSHOT_MAX_AGE = 30  # secondi


def _refresh_snapshot() -> None:
    """Copia il DB in /tmp per evitare conflitti di lock con il dashboard."""
    try:
        age = (
            time.time() - os.path.getmtime(SNAPSHOT_PATH)
            if os.path.exists(SNAPSHOT_PATH)
            else float("inf")
        )
        if age > SNAPSHOT_MAX_AGE:
            print(f"[snapshot] Copying {DB_PATH} -> {SNAPSHOT_PATH} ...", flush=True)
            shutil.copy2(DB_PATH, SNAPSHOT_PATH)
            print(f"[snapshot] Copy OK ({os.path.getsize(SNAPSHOT_PATH)} bytes)", flush=True)
            # Rimuovi WAL dallo snapshot: vogliamo un DB pulito/standalone
            snap_wal = SNAPSHOT_PATH + ".wal"
            if os.path.exists(snap_wal):
                os.remove(snap_wal)
    except Exception as e:
        print(f"[snapshot] FAILED: {type(e).__name__}: {e}", flush=True)

app = FastAPI(
    title="Personal Finance API",
    description="Espone i dati finanziari personali per agenti AI",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def get_con():
    _refresh_snapshot()
    if not os.path.exists(SNAPSHOT_PATH):
        raise HTTPException(
            status_code=503,
            detail=f"Snapshot non disponibile: impossibile leggere {DB_PATH}",
        )
    try:
        # Connessione read-write allo snapshot (è nostro, nessun altro lo usa)
        return duckdb.connect(SNAPSHOT_PATH)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database non disponibile: {e}")


def _period_filter(year: Optional[int], month: Optional[int]) -> str:
    """Returns SQL WHERE clause fragment for period filtering."""
    if year and month:
        return f"AND YEAR(date) = {year} AND MONTH(date) = {month}"
    if year:
        return f"AND YEAR(date) = {year}"
    return ""


# ---------------------------------------------------------------------------
# SUMMARY
# ---------------------------------------------------------------------------

@app.get("/summary", summary="Riepilogo finanziario del periodo")
def get_summary(
    year: Optional[int] = Query(None, description="Anno (default: anno corrente)"),
    month: Optional[int] = Query(None, description="Mese 1-12 (default: mese corrente)"),
):
    """
    Restituisce income, expenses, net balance, savings rate e confronto
    con il periodo precedente.
    """
    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    con = get_con()
    try:
        period_filter = f"YEAR(date) = {year} AND MONTH(date) = {month}"

        row = con.execute(f"""
            SELECT
                COALESCE(SUM(CASE WHEN type='Income' THEN amount ELSE 0 END), 0) AS income,
                COALESCE(SUM(CASE WHEN type='Expense' THEN ABS(amount) ELSE 0 END), 0) AS expenses,
                COALESCE(SUM(amount), 0) AS net_balance
            FROM transactions
            WHERE {period_filter}
        """).fetchone()

        income, expenses, net_balance = row
        savings_rate = round((net_balance / income * 100), 1) if income > 0 else 0

        # Previous month
        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        prev_filter = f"YEAR(date) = {prev_year} AND MONTH(date) = {prev_month}"

        prev = con.execute(f"""
            SELECT
                COALESCE(SUM(CASE WHEN type='Income' THEN amount ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN type='Expense' THEN ABS(amount) ELSE 0 END), 0)
            FROM transactions
            WHERE {prev_filter}
        """).fetchone()

        prev_income, prev_expenses = prev

        # Total liquidity (all time)
        liquidity = con.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions"
        ).fetchone()[0]

        days_in_month = calendar.monthrange(year, month)[1]

        return {
            "period": {"year": year, "month": month},
            "income": round(income, 2),
            "expenses": round(expenses, 2),
            "net_balance": round(net_balance, 2),
            "savings_rate_pct": savings_rate,
            "daily_burn_rate": round(expenses / days_in_month, 2),
            "total_liquidity": round(liquidity, 2),
            "vs_prev_month": {
                "income_delta": round(income - prev_income, 2),
                "expenses_delta": round(expenses - prev_expenses, 2),
                "income_delta_pct": round((income - prev_income) / prev_income * 100, 1) if prev_income > 0 else None,
                "expenses_delta_pct": round((expenses - prev_expenses) / prev_expenses * 100, 1) if prev_expenses > 0 else None,
            },
        }
    finally:
        con.close()


# ---------------------------------------------------------------------------
# TRANSACTIONS
# ---------------------------------------------------------------------------

@app.get("/transactions", summary="Lista transazioni filtrata")
def get_transactions(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    type: Optional[str] = Query(None, description="Expense | Income"),
    necessity: Optional[str] = Query(None, description="Need | Want"),
    limit: int = Query(50, le=500),
):
    con = get_con()
    try:
        wheres = ["1=1"]
        if year:
            wheres.append(f"YEAR(date) = {year}")
        if month:
            wheres.append(f"MONTH(date) = {month}")
        if category:
            wheres.append(f"LOWER(category) = LOWER('{category}')")
        if type:
            wheres.append(f"type = '{type}'")
        if necessity:
            wheres.append(f"necessity = '{necessity}'")

        where_clause = " AND ".join(wheres)
        rows = con.execute(f"""
            SELECT date, description, category, ABS(amount) as amount,
                   type, necessity, tags, account
            FROM transactions
            WHERE {where_clause}
            ORDER BY date DESC
            LIMIT {limit}
        """).fetchall()

        return {
            "count": len(rows),
            "transactions": [
                {
                    "date": str(r[0]),
                    "description": r[1],
                    "category": r[2],
                    "amount": round(r[3], 2),
                    "type": r[4],
                    "necessity": r[5],
                    "tags": list(r[6]) if r[6] else [],
                    "account": r[7],
                }
                for r in rows
            ],
        }
    finally:
        con.close()


# ---------------------------------------------------------------------------
# CATEGORIES
# ---------------------------------------------------------------------------

@app.get("/categories", summary="Breakdown spese per categoria")
def get_categories(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
):
    con = get_con()
    try:
        pf = _period_filter(year, month)
        rows = con.execute(f"""
            SELECT
                category,
                SUM(ABS(amount)) AS total,
                COUNT(*) AS count,
                AVG(ABS(amount)) AS avg_amount,
                ANY_VALUE(necessity) AS necessity
            FROM transactions
            WHERE type = 'Expense' AND category IS NOT NULL {pf}
            GROUP BY category
            ORDER BY total DESC
        """).fetchall()

        total_expenses = sum(r[1] for r in rows)

        return {
            "total_expenses": round(total_expenses, 2),
            "categories": [
                {
                    "name": r[0],
                    "total": round(r[1], 2),
                    "pct_of_total": round(r[1] / total_expenses * 100, 1) if total_expenses > 0 else 0,
                    "transaction_count": r[2],
                    "avg_transaction": round(r[3], 2),
                    "necessity": r[4],
                }
                for r in rows
            ],
        }
    finally:
        con.close()


# ---------------------------------------------------------------------------
# TRENDS
# ---------------------------------------------------------------------------

@app.get("/trends", summary="Trend mensile entrate/uscite")
def get_trends(months: int = Query(6, le=24)):
    con = get_con()
    try:
        rows = con.execute(f"""
            SELECT
                YEAR(date) AS year,
                MONTH(date) AS month,
                SUM(CASE WHEN type='Income' THEN amount ELSE 0 END) AS income,
                SUM(CASE WHEN type='Expense' THEN ABS(amount) ELSE 0 END) AS expenses
            FROM transactions
            GROUP BY 1, 2
            ORDER BY 1 DESC, 2 DESC
            LIMIT {months}
        """).fetchall()

        # Reverse to chronological order
        rows = list(reversed(rows))

        return {
            "months": [
                {
                    "year": r[0],
                    "month": r[1],
                    "label": f"{r[0]}-{r[1]:02d}",
                    "income": round(r[2], 2),
                    "expenses": round(r[3], 2),
                    "net": round(r[2] - r[3], 2),
                }
                for r in rows
            ]
        }
    finally:
        con.close()


# ---------------------------------------------------------------------------
# RECURRING EXPENSES
# ---------------------------------------------------------------------------

@app.get("/recurring", summary="Spese ricorrenti attive")
def get_recurring():
    con = get_con()
    try:
        rows = con.execute("""
            SELECT name, amount, category, frequency, next_date, account,
                   remaining_installments, end_date
            FROM recurring_expenses
            ORDER BY next_date
        """).fetchall()

        def to_monthly(amount, freq):
            if freq == "Monthly": return amount
            if freq == "Yearly": return round(amount / 12, 2)
            if freq == "Weekly": return round(amount * 4.33, 2)
            return amount

        items = [
            {
                "name": r[0],
                "amount": round(r[1], 2),
                "category": r[2],
                "frequency": r[3],
                "next_date": str(r[4]),
                "account": r[5],
                "remaining_installments": r[6],
                "end_date": str(r[7]) if r[7] else None,
                "monthly_equivalent": to_monthly(r[1], r[3]),
            }
            for r in rows
        ]

        total_monthly = sum(i["monthly_equivalent"] for i in items)

        return {
            "count": len(items),
            "total_monthly_commitment": round(total_monthly, 2),
            "total_annual_commitment": round(total_monthly * 12, 2),
            "items": items,
        }
    finally:
        con.close()


# ---------------------------------------------------------------------------
# INSIGHTS
# ---------------------------------------------------------------------------

@app.get("/insights", summary="Insight avanzati: anomalie, top merchant, need vs want")
def get_insights(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
):
    con = get_con()
    try:
        pf = _period_filter(year, month)

        # Need vs Want
        nw = con.execute(f"""
            SELECT necessity, SUM(ABS(amount)) AS total
            FROM transactions
            WHERE type='Expense' {pf}
            GROUP BY necessity
        """).fetchall()
        nw_dict = {r[0]: round(r[1], 2) for r in nw if r[0]}

        # Top merchants (≥2 transactions)
        merchants = con.execute(f"""
            SELECT description, COUNT(*) AS cnt, SUM(ABS(amount)) AS total, AVG(ABS(amount)) AS avg
            FROM transactions
            WHERE type='Expense' {pf}
            GROUP BY description
            HAVING COUNT(*) >= 2
            ORDER BY total DESC
            LIMIT 10
        """).fetchall()

        # Anomalies: per category, transactions > mean + 2*std
        anomalies_raw = con.execute(f"""
            SELECT category, description, date, ABS(amount) as amount,
                   AVG(ABS(amount)) OVER (PARTITION BY category) AS cat_avg,
                   STDDEV(ABS(amount)) OVER (PARTITION BY category) AS cat_std
            FROM transactions
            WHERE type='Expense' AND category IS NOT NULL {pf}
        """).df()

        anomalies = []
        if not anomalies_raw.empty:
            anomalies_raw = anomalies_raw[anomalies_raw['cat_std'] > 0]
            anomalies_raw['z'] = (anomalies_raw['amount'] - anomalies_raw['cat_avg']) / anomalies_raw['cat_std']
            flagged = anomalies_raw[anomalies_raw['z'] > 2].sort_values('z', ascending=False).head(5)
            for _, row in flagged.iterrows():
                anomalies.append({
                    "date": str(row['date']),
                    "description": row['description'],
                    "category": row['category'],
                    "amount": round(row['amount'], 2),
                    "category_avg": round(row['cat_avg'], 2),
                    "z_score": round(row['z'], 1),
                })

        # Savings rate
        totals = con.execute(f"""
            SELECT
                SUM(CASE WHEN type='Income' THEN amount ELSE 0 END) AS income,
                SUM(CASE WHEN type='Expense' THEN ABS(amount) ELSE 0 END) AS expenses
            FROM transactions WHERE 1=1 {pf}
        """).fetchone()
        income_total, expenses_total = totals
        savings_rate = round((income_total - expenses_total) / income_total * 100, 1) if income_total > 0 else None

        return {
            "savings_rate_pct": savings_rate,
            "need_vs_want": {
                "need": nw_dict.get("Need", 0),
                "want": nw_dict.get("Want", 0),
                "need_pct": round(nw_dict.get("Need", 0) / (nw_dict.get("Need", 0) + nw_dict.get("Want", 0)) * 100, 1)
                if (nw_dict.get("Need", 0) + nw_dict.get("Want", 0)) > 0 else None,
            },
            "top_merchants": [
                {"name": r[0], "transactions": r[1], "total": round(r[2], 2), "avg": round(r[3], 2)}
                for r in merchants
            ],
            "anomalies": anomalies,
        }
    finally:
        con.close()


# ---------------------------------------------------------------------------
# HEALTH
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    try:
        con = get_con()
        count = con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        con.close()
        return {"status": "ok", "transactions": count}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
