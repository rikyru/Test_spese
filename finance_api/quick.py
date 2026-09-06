"""
Pagina rapida per il telefono (/quick).

Serve una singola pagina web installabile sulla home di Android e i pochi
endpoint che le servono. Le scritture NON toccano DuckDB: il dashboard Streamlit
tiene una connessione read-write permanente sul file e DuckDB non ammette un
secondo writer, quindi qui si accoda su `inbox.jsonl` e il dashboard travasa in
DB al primo avvio utile (`DataManager.drain_inbox`).
"""

import json
import math
import os
import struct
import threading
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
# Icona: disegnata con funzioni di distanza e antialiasing, senza dipendenze
# grafiche (Pillow sarebbe l'unica libreria pesante, solo per due file statici).
# ---------------------------------------------------------------------------

_BG_TOP = (26, 42, 66)      # slate scuro, in alto
_BG_BOT = (11, 18, 32)      # quasi nero, in basso
_GLOW = (34, 197, 94)       # alone verde dietro il simbolo
_FG_TOP = (134, 239, 172)   # verde chiaro
_FG_BOT = (34, 197, 94)     # verde pieno


def _sd_round_box(px, py, hw, hh, r):
    """Distanza con segno da un rettangolo a spigoli arrotondati."""
    qx, qy = abs(px) - hw + r, abs(py) - hh + r
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r


def _sd_euro(px, py):
    """Distanza con segno dal simbolo €: un arco aperto a destra e due sbarre."""
    # Arco (la "C"), con estremita' arrotondate
    cx, r_mid, half_w, cut = 0.06, 0.60, 0.095, math.radians(40)
    vx, vy = px - cx, py
    rad = math.hypot(vx, vy)
    if abs(math.atan2(vy, vx)) > cut:
        d = abs(rad - r_mid) - half_w
    else:
        ex, ey = cx + r_mid * math.cos(cut), r_mid * math.sin(cut)
        d = min(math.hypot(px - ex, py - ey), math.hypot(px - ex, py + ey)) - half_w
    # Le due sbarre orizzontali
    for by in (-0.17, 0.17):
        d = min(d, _sd_round_box(px + 0.19, py - by, 0.61, 0.075, 0.075))
    return d


def _render(size: int, maskable: bool) -> bytes:
    """RGB `size`x`size` con supersampling 2x. `maskable`: sfondo a tutto campo
    e simbolo piu' piccolo, perche' Android ritaglia i bordi con la sua forma."""
    ss = 2
    n = size * ss
    glyph_scale = 0.62 if maskable else 0.78
    corner = None if maskable else 0.46
    px_norm = 2.0 / n

    # 1) Accumulo a risoluzione doppia, 2) media a blocchi -> antialiasing.
    acc = [[0.0] * (size * 3) for _ in range(size)]
    for iy in range(n):
        y = (iy + 0.5) / n * 2 - 1
        oy = iy // ss
        arow = acc[oy]
        for ix in range(n):
            x = (ix + 0.5) / n * 2 - 1

            # Sfondo: sfumatura verticale + alone verde dietro al simbolo
            t = (y + 1) / 2
            glow = max(0.0, 1.0 - math.hypot(x, y + 0.05) / 1.15) ** 2.4 * 0.30
            r = _BG_TOP[0] + (_BG_BOT[0] - _BG_TOP[0]) * t + _GLOW[0] * glow
            g = _BG_TOP[1] + (_BG_BOT[1] - _BG_TOP[1]) * t + _GLOW[1] * glow
            b = _BG_TOP[2] + (_BG_BOT[2] - _BG_TOP[2]) * t + _GLOW[2] * glow

            # Simbolo sopra lo sfondo, con copertura sfumata sul bordo
            cov = min(max(0.5 - _sd_euro(x / glyph_scale, y / glyph_scale)
                          * glyph_scale / px_norm, 0.0), 1.0)
            if cov > 0:
                tf = (y + 1) / 2
                r += (_FG_TOP[0] + (_FG_BOT[0] - _FG_TOP[0]) * tf - r) * cov
                g += (_FG_TOP[1] + (_FG_BOT[1] - _FG_TOP[1]) * tf - g) * cov
                b += (_FG_TOP[2] + (_FG_BOT[2] - _FG_TOP[2]) * tf - b) * cov

            # Angoli arrotondati solo per l'icona non-maskable
            if corner is not None:
                out = min(max(0.5 + _sd_round_box(x, y, 1.0, 1.0, corner)
                              / px_norm, 0.0), 1.0)
                if out > 0:
                    r *= 1 - out
                    g *= 1 - out
                    b *= 1 - out

            ox = (ix // ss) * 3
            arow[ox] += r
            arow[ox + 1] += g
            arow[ox + 2] += b

    div = float(ss * ss)
    rows = []
    for arow in acc:
        row = bytearray([0])  # filter byte: none
        row += bytes(min(255, int(v / div + 0.5)) for v in arow)
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
_ICON_LOCK = threading.Lock()


def _icon_bytes(size: int, maskable: bool) -> bytes:
    key = (size, maskable)
    with _ICON_LOCK:
        if key not in _ICON_CACHE:
            _ICON_CACHE[key] = _render(size, maskable)
        return _ICON_CACHE[key]


def _warm_icons() -> None:
    """Le icone sono uguali per sempre: si generano una volta all'avvio, cosi'
    l'installazione sulla home non aspetta il rendering."""
    for size in (192, 512):
        for maskable in (False, True):
            try:
                _icon_bytes(size, maskable)
            except Exception:
                pass


threading.Thread(target=_warm_icons, daemon=True).start()


@router.get("/icon-{size}.png", include_in_schema=False)
def icon(size: int):
    if size not in (192, 512):
        raise HTTPException(status_code=404, detail="Not found")
    return Response(
        content=_icon_bytes(size, maskable=False),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/icon-maskable-{size}.png", include_in_schema=False)
def icon_maskable(size: int):
    if size not in (192, 512):
        raise HTTPException(status_code=404, detail="Not found")
    return Response(
        content=_icon_bytes(size, maskable=True),
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
                {"src": "/quick/icon-192.png", "sizes": "192x192",
                 "type": "image/png", "purpose": "any"},
                {"src": "/quick/icon-512.png", "sizes": "512x512",
                 "type": "image/png", "purpose": "any"},
                {"src": "/quick/icon-maskable-192.png", "sizes": "192x192",
                 "type": "image/png", "purpose": "maskable"},
                {"src": "/quick/icon-maskable-512.png", "sizes": "512x512",
                 "type": "image/png", "purpose": "maskable"},
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
