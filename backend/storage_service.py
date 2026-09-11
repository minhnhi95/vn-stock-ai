"""
Persistence layer: sổ giao dịch thật, cảnh báo, tín hiệu AI.

Dual driver:
- Có DATABASE_URL bắt đầu bằng "postgres" → dùng Neon Postgres (production)
- Còn lại → SQLite local (dev)

Cùng schema, cùng API public. Code gọi `list_real_transactions()`,
`insert_alert_rule()`... không cần biết backend nào.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_POSTGRES = DATABASE_URL.startswith("postgres")

DB_PATH = Path(os.getenv("STOCK_DB_PATH", Path(__file__).parent / "data.db"))
_init_lock = threading.Lock()
_initialized = False

# --- Postgres pool (chỉ khởi tạo khi cần) ---
_pg_pool = None
_pool_opened = False
_pool_open_lock = threading.Lock()
if USE_POSTGRES:
    try:
        from psycopg_pool import ConnectionPool
        from psycopg.rows import dict_row
        # Neon yêu cầu sslmode=require; thường đã trong URL
        _pg_pool = ConnectionPool(
            DATABASE_URL,
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row},
            open=False,  # open lazily lần đầu dùng
        )
    except ImportError as e:
        print(f"[storage] psycopg chưa cài: {e}. Fallback SQLite.")
        USE_POSTGRES = False


@contextmanager
def _conn():
    """Yield connection (sqlite3.Connection hoặc psycopg.Connection)."""
    global _pool_opened
    if USE_POSTGRES:
        # Open pool 1 lần duy nhất (thread-safe).
        if not _pool_opened:
            with _pool_open_lock:
                if not _pool_opened:
                    _pg_pool.open(wait=True, timeout=30)
                    _pool_opened = True
        with _pg_pool.connection() as con:
            yield con
    else:
        con = sqlite3.connect(DB_PATH, isolation_level=None, check_same_thread=False)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA foreign_keys=ON")
            yield con
        finally:
            con.close()


def _execute(con, sql: str, params: tuple = ()):
    """Adapter exec — chuyển ? sang %s cho Postgres."""
    if USE_POSTGRES:
        sql = sql.replace("?", "%s")
        cur = con.cursor()
        cur.execute(sql, params)
        return cur
    else:
        return con.execute(sql, params)


def _fetchone(con, sql: str, params: tuple = ()):
    cur = _execute(con, sql, params)
    if USE_POSTGRES:
        return cur.fetchone()
    return cur.fetchone()


def _fetchall(con, sql: str, params: tuple = ()):
    cur = _execute(con, sql, params)
    return cur.fetchall()


def _begin(con):
    """Bắt đầu transaction."""
    if USE_POSTGRES:
        # psycopg 3 với autocommit=False tự begin transaction implicit khi có statement.
        # KHÔNG gọi BEGIN explicit vì transaction đã active từ statement trước.
        # Mặc định READ COMMITTED đủ cho use case 1 user 1 portfolio.
        pass
    else:
        con.execute("BEGIN IMMEDIATE")


def _commit(con):
    if USE_POSTGRES:
        con.commit()
    else:
        con.execute("COMMIT")


def _rollback(con):
    if USE_POSTGRES:
        con.rollback()
    else:
        con.execute("ROLLBACK")


SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS alert (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    condition TEXT NOT NULL,
    threshold REAL NOT NULL,
    created_at INTEGER NOT NULL,
    triggered_at INTEGER,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_alert_symbol ON alert(symbol);
CREATE TABLE IF NOT EXISTS real_txn (
    id TEXT PRIMARY KEY,
    ext_id TEXT UNIQUE,
    trade_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    fee REAL NOT NULL DEFAULT 0,
    tax REAL NOT NULL DEFAULT 0,
    note TEXT,
    source TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_real_txn_symbol ON real_txn(symbol, trade_date);
CREATE TABLE IF NOT EXISTS daily_brief (
    brief_date TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    model TEXT,
    generated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS verdict_scan (
    scan_date TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    generated_at INTEGER NOT NULL
);
"""

SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS alert (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    condition TEXT NOT NULL,
    threshold DOUBLE PRECISION NOT NULL,
    created_at BIGINT NOT NULL,
    triggered_at BIGINT,
    active BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_alert_symbol ON alert(symbol);
CREATE TABLE IF NOT EXISTS real_txn (
    id TEXT PRIMARY KEY,
    ext_id TEXT UNIQUE,
    trade_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity BIGINT NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    fee DOUBLE PRECISION NOT NULL DEFAULT 0,
    tax DOUBLE PRECISION NOT NULL DEFAULT 0,
    note TEXT,
    source TEXT,
    created_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_real_txn_symbol ON real_txn(symbol, trade_date);
CREATE TABLE IF NOT EXISTS daily_brief (
    brief_date TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    model TEXT,
    generated_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS verdict_scan (
    scan_date TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    generated_at BIGINT NOT NULL
);
"""


def _init_schema_once():
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        with _conn() as con:
            if USE_POSTGRES:
                # psycopg cần execute từng statement
                for stmt in SCHEMA_PG.split(";"):
                    s = stmt.strip()
                    if s:
                        con.execute(s)
                con.commit()
            else:
                con.executescript(SCHEMA_SQLITE)

        _initialized = True


def _row_get(row, key):
    """Compat: sqlite3.Row dùng [] index, psycopg dict_row dùng dict."""
    if row is None:
        return None
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


# ---------- Alert rules ----------
# Dùng chung DB với portfolio để alert sống sót qua redeploy và nhìn thấy được
# từ mọi gunicorn worker (file JSON trước đây không đảm bảo cả hai).

def _alert_row_to_dict(row) -> Dict[str, Any]:
    """SQLite lưu active dạng 0/1, Postgres dạng boolean — chuẩn hoá về bool."""
    return {
        "id": _row_get(row, "id"),
        "symbol": _row_get(row, "symbol"),
        "condition": _row_get(row, "condition"),
        "threshold": _row_get(row, "threshold"),
        "created_at": _row_get(row, "created_at"),
        "triggered_at": _row_get(row, "triggered_at"),
        "active": bool(_row_get(row, "active")),
    }


def list_alert_rules(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    """Alerts mới nhất trước. `symbol` lọc theo mã (đã uppercase từ caller)."""
    _init_schema_once()
    with _conn() as con:
        if symbol:
            rows = _fetchall(
                con,
                "SELECT id, symbol, condition, threshold, created_at, triggered_at, active "
                "FROM alert WHERE symbol = ? ORDER BY created_at DESC",
                (symbol,),
            )
        else:
            rows = _fetchall(
                con,
                "SELECT id, symbol, condition, threshold, created_at, triggered_at, active "
                "FROM alert ORDER BY created_at DESC",
            )
    return [_alert_row_to_dict(r) for r in rows]


def insert_alert_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    """Ghi rule mới. Caller đã validate symbol/condition/threshold."""
    _init_schema_once()
    with _conn() as con:
        _begin(con)
        _execute(
            con,
            "INSERT INTO alert(id, symbol, condition, threshold, created_at, triggered_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                rule["id"],
                rule["symbol"],
                rule["condition"],
                float(rule["threshold"]),
                int(rule["created_at"]),
                rule.get("triggered_at"),
                True if USE_POSTGRES else 1,
            ),
        )
        _commit(con)
    return dict(rule)


def delete_alert_rule(alert_id: str) -> bool:
    """True nếu có dòng bị xoá."""
    _init_schema_once()
    with _conn() as con:
        _begin(con)
        cur = _execute(con, "DELETE FROM alert WHERE id = ?", (alert_id,))
        deleted = (cur.rowcount or 0) > 0
        _commit(con)
    return deleted


def mark_alert_rule_triggered(alert_id: str, triggered_at: int) -> None:
    """One-shot: đánh dấu đã bắn và tắt rule. Idempotent."""
    _init_schema_once()
    with _conn() as con:
        _begin(con)
        _execute(
            con,
            "UPDATE alert SET triggered_at = ?, active = ? WHERE id = ?",
            (int(triggered_at), False if USE_POSTGRES else 0, alert_id),
        )
        _commit(con)


# ---------- Giao dịch thật ----------
# Sổ giao dịch thật của người dùng: mất là không khôi phục được.

def _real_txn_to_dict(row) -> Dict[str, Any]:
    return {
        "id": _row_get(row, "id"),
        "ext_id": _row_get(row, "ext_id"),
        "date": _row_get(row, "trade_date"),
        "symbol": _row_get(row, "symbol"),
        "side": _row_get(row, "side"),
        "quantity": _row_get(row, "quantity"),
        "price": _row_get(row, "price"),
        "fee": _row_get(row, "fee") or 0.0,
        "tax": _row_get(row, "tax") or 0.0,
        "note": _row_get(row, "note") or "",
        "source": _row_get(row, "source") or "",
    }


_REAL_TXN_COLUMNS = (
    "id, ext_id, trade_date, symbol, side, quantity, price, fee, tax, note, source"
)


def list_real_transactions(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    """Toàn bộ sổ giao dịch thật, cũ trước — thứ tự này cần cho khớp lệnh FIFO."""
    _init_schema_once()
    with _conn() as con:
        if symbol:
            rows = _fetchall(
                con,
                f"SELECT {_REAL_TXN_COLUMNS} FROM real_txn WHERE symbol = ? "
                "ORDER BY trade_date ASC, created_at ASC",
                (symbol,),
            )
        else:
            rows = _fetchall(
                con,
                f"SELECT {_REAL_TXN_COLUMNS} FROM real_txn "
                "ORDER BY trade_date ASC, created_at ASC",
            )
    return [_real_txn_to_dict(r) for r in rows]


def insert_real_transactions(records: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Ghi nhiều giao dịch, bỏ qua bản ghi đã có `ext_id` trùng.

    Trả {"inserted": n, "skipped": n} — người dùng cần biết lần nhập này thực sự
    thêm bao nhiêu dòng, vì sao kê các tháng thường chồng lấn nhau.
    """
    _init_schema_once()
    if not records:
        return {"inserted": 0, "skipped": 0}

    existing = set()
    with _conn() as con:
        rows = _fetchall(con, "SELECT ext_id FROM real_txn WHERE ext_id IS NOT NULL")
        existing = {_row_get(r, "ext_id") for r in rows}

        inserted = 0
        skipped = 0
        _begin(con)
        try:
            for rec in records:
                ext_id = rec.get("ext_id")
                if ext_id and ext_id in existing:
                    skipped += 1
                    continue
                _execute(
                    con,
                    "INSERT INTO real_txn(id, ext_id, trade_date, symbol, side, quantity, "
                    "price, fee, tax, note, source, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        rec["id"],
                        ext_id,
                        rec["date"],
                        rec["symbol"],
                        rec["side"],
                        int(rec["quantity"]),
                        float(rec["price"]),
                        float(rec.get("fee") or 0.0),
                        float(rec.get("tax") or 0.0),
                        rec.get("note") or "",
                        rec.get("source") or "",
                        int(time.time()),
                    ),
                )
                if ext_id:
                    existing.add(ext_id)
                inserted += 1
            _commit(con)
        except Exception:
            _rollback(con)
            raise

    return {"inserted": inserted, "skipped": skipped}


def delete_real_transaction(txn_id: str) -> bool:
    _init_schema_once()
    with _conn() as con:
        _begin(con)
        cur = _execute(con, "DELETE FROM real_txn WHERE id = ?", (txn_id,))
        deleted = (cur.rowcount or 0) > 0
        _commit(con)
    return deleted


def clear_real_transactions() -> int:
    """Xoá toàn bộ sổ giao dịch thật. Trả số dòng đã xoá để UI xác nhận lại."""
    _init_schema_once()
    with _conn() as con:
        _begin(con)
        cur = _execute(con, "DELETE FROM real_txn")
        deleted = cur.rowcount or 0
        _commit(con)
    return deleted


# ---------- Bản tin hằng ngày ----------
# Job chạy nền (jobs/daily_brief.py) ghi vào đây; API chỉ đọc ra. Nhờ vậy app
# web không cần gọi AI lúc phục vụ request — mở lên là có ngay.

def save_daily_brief(brief_date: str, payload: Dict[str, Any]) -> None:
    """Ghi đè bản tin của ngày. Chạy lại job trong ngày sẽ cập nhật bản mới."""
    _init_schema_once()
    with _conn() as con:
        _begin(con)
        _execute(
            con,
            "INSERT INTO daily_brief(brief_date, payload, model, generated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (brief_date) DO UPDATE SET payload = EXCLUDED.payload, "
            "model = EXCLUDED.model, generated_at = EXCLUDED.generated_at",
            (
                brief_date,
                json.dumps(payload, ensure_ascii=False),
                payload.get("model", ""),
                int(time.time()),
            ),
        )
        _commit(con)


def get_daily_brief(brief_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Bản tin của một ngày, hoặc bản mới nhất nếu không truyền ngày."""
    _init_schema_once()
    with _conn() as con:
        if brief_date:
            row = _fetchone(
                con,
                "SELECT brief_date, payload, model, generated_at FROM daily_brief WHERE brief_date = ?",
                (brief_date,),
            )
        else:
            row = _fetchone(
                con,
                "SELECT brief_date, payload, model, generated_at FROM daily_brief "
                "ORDER BY brief_date DESC LIMIT 1",
            )
    if not row:
        return None

    try:
        payload = json.loads(_row_get(row, "payload"))
    except (TypeError, ValueError):
        return None
    payload["brief_date"] = _row_get(row, "brief_date")
    payload["stored_at"] = _row_get(row, "generated_at")
    return payload


def list_brief_dates(limit: int = 30) -> List[str]:
    """Các ngày đã có bản tin, mới nhất trước."""
    _init_schema_once()
    with _conn() as con:
        rows = _fetchall(
            con,
            "SELECT brief_date FROM daily_brief ORDER BY brief_date DESC LIMIT ?",
            (limit,),
        )
    return [_row_get(r, "brief_date") for r in rows]


# ---------- Quét kết luận cả rổ ----------
# Job chạy nền (jobs/verdict_scan.py) ghi mỗi ngày một dòng; API và cảnh báo chỉ
# đọc. Giữ theo ngày để so được kết luận hôm nay với phiên trước.

def save_verdict_scan(scan_date: str, payload: Dict[str, Any]) -> None:
    """Ghi đè lượt quét của ngày. Chạy lại job trong ngày sẽ thay bằng lượt mới."""
    _init_schema_once()
    with _conn() as con:
        _begin(con)
        _execute(
            con,
            "INSERT INTO verdict_scan(scan_date, payload, generated_at) VALUES (?, ?, ?) "
            "ON CONFLICT (scan_date) DO UPDATE SET payload = EXCLUDED.payload, "
            "generated_at = EXCLUDED.generated_at",
            (scan_date, json.dumps(payload, ensure_ascii=False), int(time.time())),
        )
        _commit(con)


def _scan_row_to_dict(row) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    try:
        payload = json.loads(_row_get(row, "payload"))
    except (TypeError, ValueError):
        return None
    payload["scan_date"] = _row_get(row, "scan_date")
    payload["stored_at"] = _row_get(row, "generated_at")
    return payload


def get_verdict_scan(scan_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Lượt quét của một ngày, hoặc lượt mới nhất nếu không truyền ngày."""
    _init_schema_once()
    with _conn() as con:
        if scan_date:
            row = _fetchone(
                con,
                "SELECT scan_date, payload, generated_at FROM verdict_scan WHERE scan_date = ?",
                (scan_date,),
            )
        else:
            row = _fetchone(
                con,
                "SELECT scan_date, payload, generated_at FROM verdict_scan "
                "ORDER BY scan_date DESC LIMIT 1",
            )
    return _scan_row_to_dict(row)


def get_previous_verdict_scan(before_date: str) -> Optional[Dict[str, Any]]:
    """Lượt quét gần nhất TRƯỚC một ngày — mốc để tìm mã vừa đổi kết luận."""
    _init_schema_once()
    with _conn() as con:
        row = _fetchone(
            con,
            "SELECT scan_date, payload, generated_at FROM verdict_scan "
            "WHERE scan_date < ? ORDER BY scan_date DESC LIMIT 1",
            (before_date,),
        )
    return _scan_row_to_dict(row)


def list_verdict_scan_dates(limit: int = 30) -> List[str]:
    """Các ngày đã có lượt quét, mới nhất trước."""
    _init_schema_once()
    with _conn() as con:
        rows = _fetchall(
            con,
            "SELECT scan_date FROM verdict_scan ORDER BY scan_date DESC LIMIT ?",
            (limit,),
        )
    return [_row_get(r, "scan_date") for r in rows]
