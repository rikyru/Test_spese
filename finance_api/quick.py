"""
Pagina rapida per il telefono (/quick).

Serve una singola pagina web installabile sulla home di Android e i pochi
endpoint che le servono. Le scritture NON toccano DuckDB: il dashboard Streamlit
tiene una connessione read-write permanente sul file e DuckDB non ammette un
secondo writer, quindi qui si accoda su `inbox.jsonl` e il dashboard travasa in
DB al primo avvio utile (`DataManager.drain_inbox`).
"""

import json
import os
import struct
import zlib
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

INBOX_DIR = os.getenv("INBOX_DIR", "/app/inbox")
INBOX_PATH = os.path.join(INBOX_DIR, "inbox.jsonl")
RULES_PATH = os.getenv("RULES_PATH", "/app/data/rules.yaml")
HERE = Path(__file__).parent

router = APIRouter(prefix="/quick")


# ---------------------------------------------------------------------------
# Icona: PNG generato a mano (niente Pillow nell'immagine, sarebbe l'unica dipendenza
# pesante solo per due file statici).
# ---------------------------------------------------------------------------

_EURO_MASK = [
    "................",
    "................",
    "................",
    ".....xxxxxxx....",
    "....xx.....xx...",
    "...xx........x..",
    "...xx...........",
    "..xxxxxxxx......",
    "...xx...........",
    "..xxxxxxxx......",
    "...xx...........",
    "...xx........x..",
    "....xx.....xx...",
    ".....xxxxxxx....",
    "................",
    "................",
]

_BG = (16, 24, 39)      # slate-900
_FG = (74, 222, 128)    # green-400


def _png(size: int) -> bytes:
    """Renderizza la maschera ASCII come PNG RGB a `size` px (nearest neighbour)."""
    mh, mw = len(_EURO_MASK), len(_EURO_MASK[0])
    rows = []
    for y in range(size):
        row = bytearray([0])  # filter byte: none
        my = y * mh // size
        line = _EURO_MASK[my]
        for x in range(size):
            row += bytes(_FG if line[x * mw // size] != "." else _BG)
        rows.append(bytes(row))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )


_ICON_CACHE: dict = {}


@router.get("/icon-{size}.png", include_in_schema=False)
def icon(size: int):
    if size not in (192, 512):
        raise HTTPException(status_code=404, detail="Not found")
    if size not in _ICON_CACHE:
        _ICON_CACHE[size] = _png(size)
    return Response(
        content=_ICON_CACHE[size],
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return JSONResponse(
        {
            "name": "Spese",
            "short_name": "Spese",
            "start_url": "/quick",
            "scope": "/quick",
            "display": "standalone",
            "background_color": "#0f172a",
            "theme_color": "#0f172a",
            "shortcuts": [
                {
                    "name": "Nuova spesa",
                    "short_name": "Nuova",
                    "url": "/quick#new",
                    "icons": [{"src": "/quick/icon-192.png", "sizes": "192x192"}],
                }
            ],
            "icons": [
                {
                    "src": "/quick/icon-192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
                {
                    "src": "/quick/icon-512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
            ],
        },
        media_type="application/manifest+json",
    )


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
def page():
    return FileResponse(HERE / "quick.html", media_type="text/html")


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------

def _read_inbox() -> List[dict]:
    """Righe accodate e non ancora travasate nel DB (inbox + eventuale staging)."""
    out = []
    for path in (INBOX_PATH + ".processing", INBOX_PATH):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            continue
    return out


def _append_inbox(entry: dict) -> None:
    os.makedirs(INBOX_DIR, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    # O_APPEND: scrittura atomica per righe brevi, anche se il dashboard sta drenando
    fd = os.open(INBOX_PATH, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def _main_wallet(con) -> Optional[str]:
    try:
        import yaml
        with open(RULES_PATH, encoding="utf-8") as f:
            wallet = (yaml.safe_load(f) or {}).get("main_wallet")
        if wallet:
            return wallet
    except Exception:
        pass
    try:
        row = con.execute(
            "SELECT account FROM transactions WHERE account IS NOT NULL "
            "GROUP BY account ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Dati per la pagina
# ---------------------------------------------------------------------------

_COMBOS_SQL = """
WITH ex AS (
    SELECT category, unnest(tags) AS tag, date, abs(amount) AS amt
    FROM transactions
    WHERE type = 'Expense'
      AND (source_file IS NULL OR source_file NOT IN ('Recurring', 'reconcile'))
), f AS (
    SELECT * FROM ex
    WHERE category IS NOT NULL AND tag IS NOT NULL AND tag <> ''
      AND lower(tag) NOT IN ('recurring', 'initial', 'adjustment')
), w AS (
    SELECT *,
           pow(0.5, greatest(date_diff('day', date, (SELECT max(date) FROM f)), 0) / 30.0) AS wt,
           row_number() OVER (PARTITION BY category, tag ORDER BY date DESC) AS rn
    FROM f
)
SELECT category, tag,
       sum(wt) AS score,
       count(*) AS n,
       max(date) AS last,
       median(CASE WHEN rn <= 5 THEN amt END) AS amt
FROM w
GROUP BY 1, 2
-- almeno due usi: sui chip del telefono una spesa una-tantum molto recente
-- ruberebbe altrimenti uno degli slot visibili
HAVING count(*) >= 2
ORDER BY score DESC
LIMIT ?
"""


def _month_totals(con, year: int, month: int, pending: List[dict]) -> dict:
    row = con.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN type='Income' THEN amount ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN type='Expense' THEN ABS(amount) ELSE 0 END), 0)
        FROM transactions
        WHERE YEAR(date) = ? AND MONTH(date) = ?
        """,
        [year, month],
    ).fetchone()
    income, expenses = float(row[0]), float(row[1])

    # Lo snapshot ha fino a 30s di ritardo e la coda non e' ancora in DB:
    # sommo qui le pendenti del mese, altrimenti il totale "balla" dopo un inserimento.
    pending_count = 0
    for e in pending:
        try:
            d = datetime.fromisoformat(str(e.get("date"))[:10]).date()
        except ValueError:
            continue
        if d.year != year or d.month != month:
            continue
        amt = abs(float(e.get("amount") or 0))
        if e.get("type") == "Income":
            income += amt
        else:
            expenses += amt
        pending_count += 1

    liquidity = float(
        con.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions").fetchone()[0]
    )
    for e in pending:
        amt = abs(float(e.get("amount") or 0))
        liquidity += amt if e.get("type") == "Income" else -amt

    top = con.execute(
        """
        SELECT category, SUM(ABS(amount)) AS total
        FROM transactions
        WHERE type = 'Expense' AND category IS NOT NULL
          AND YEAR(date) = ? AND MONTH(date) = ?
        GROUP BY 1 ORDER BY 2 DESC LIMIT 5
        """,
        [year, month],
    ).fetchall()

    return {
        "year": year,
        "month": month,
        "income": round(income, 2),
        "expenses": round(expenses, 2),
        "net": round(income - expenses, 2),
        "liquidity": round(liquidity, 2),
        "pending": pending_count,
        "top_categories": [
            {"name": r[0], "total": round(float(r[1]), 2)} for r in top
        ],
    }


def build_router(get_con):
    """`get_con` e' la factory di connessione allo snapshot definita in main.py."""

    @router.get("/api/bootstrap", include_in_schema=False)
    def bootstrap():
        today = date.today()
        pending = _read_inbox()
        con = get_con()
        try:
            combos = [
                {
                    "category": r[0],
                    "tag": r[1],
                    "amount": round(float(r[5] or 0), 2),
                    "n": int(r[3]),
                }
                for r in con.execute(_COMBOS_SQL, [10]).fetchall()
            ]
            accounts = [
                r[0] for r in con.execute(
                    "SELECT DISTINCT account FROM transactions "
                    "WHERE account IS NOT NULL ORDER BY 1"
                ).fetchall() if r[0]
            ]
            categories = [
                r[0] for r in con.execute(
                    "SELECT DISTINCT category FROM transactions "
                    "WHERE category IS NOT NULL ORDER BY 1"
                ).fetchall() if r[0]
            ]
            tags = [
                r[0] for r in con.execute(
                    "SELECT DISTINCT unnest(tags) AS t FROM transactions "
                    "WHERE tags IS NOT NULL ORDER BY 1"
                ).fetchall() if r[0]
            ]
            return {
                "today": today.isoformat(),
                "combos": combos,
                "accounts": accounts,
                "categories": categories,
                "tags": tags,
                "main_wallet": _main_wallet(con),
                "totals": _month_totals(con, today.year, today.month, pending),
            }
        finally:
            con.close()

    class QuickTx(BaseModel):
        id: str = Field(..., min_length=8, max_length=64)
        amount: float = Field(..., gt=0, le=1_000_000)
        type: str = "Expense"
        date: Optional[str] = None
        category: Optional[str] = None
        account: Optional[str] = None
        description: str = ""
        tags: List[str] = []
        necessity: Optional[str] = None

    @router.post("/api/transaction", include_in_schema=False)
    def add(tx: QuickTx):
        if tx.type not in ("Expense", "Income"):
            raise HTTPException(status_code=400, detail="type deve essere Expense o Income")
        if tx.necessity not in (None, "", "Need", "Want"):
            raise HTTPException(status_code=400, detail="necessity non valida")
        try:
            d = datetime.fromisoformat(tx.date).date() if tx.date else date.today()
        except ValueError:
            raise HTTPException(status_code=400, detail="data non valida")

        entry = {
            "id": tx.id,
            "date": d.isoformat(),
            "amount": round(abs(tx.amount), 2),
            "type": tx.type,
            "category": (tx.category or "").strip() or None,
            "account": (tx.account or "").strip() or None,
            "description": tx.description.strip()[:200],
            "tags": [t.strip().lstrip("#").lower() for t in tx.tags if t.strip()][:10],
            "necessity": tx.necessity or None,
            "received_at": datetime.now().isoformat(timespec="seconds"),
        }

        pending = _read_inbox()
        if any(str(e.get("id")) == tx.id for e in pending):
            # Reinvio dalla coda offline: gia' accodata, non duplicare
            duplicate = True
        else:
            _append_inbox(entry)
            pending.append(entry)
            duplicate = False

        today = date.today()
        con = get_con()
        try:
            totals = _month_totals(con, today.year, today.month, pending)
        finally:
            con.close()
        return {"ok": True, "duplicate": duplicate, "totals": totals}

    return router
