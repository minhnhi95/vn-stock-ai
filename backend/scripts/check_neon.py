r"""
Kiểm tra tầng lưu trữ chạy đúng trên Neon/Postgres TRƯỚC khi deploy.

Vì sao cần: toàn bộ test tự động chạy trên SQLite (chúng cố tình xoá DATABASE_URL
để không đụng DB thật). Nhánh Postgres của storage_service — kiểu boolean, cú
pháp RETURNING, connection pool — chưa từng chạy ở đâu. Script này chạy một vòng
CRUD đầy đủ trên mọi bảng và báo lỗi ngay, thay vì để bạn phát hiện lúc đã lên
production.

Cách chạy:
    # PowerShell
    $env:DATABASE_URL="postgresql://user:pass@ep-xxx-pooler.../neondb?sslmode=require"
    ..\.venv\Scripts\python.exe scripts\check_neon.py

    # bash
    DATABASE_URL="postgresql://..." ../.venv/Scripts/python.exe scripts/check_neon.py

Script CHỈ ghi dữ liệu test rồi dọn sạch. Nó không đụng tới dữ liệu có sẵn của
bạn ngoài những bản ghi nó tự tạo — trừ bảng portfolio (dùng chung 1 dòng id=1),
nên đừng chạy trên DB đang có danh mục thật mà bạn quan tâm.
"""
from __future__ import annotations

import os
import sys
import traceback
import uuid
from pathlib import Path

# Cho phép chạy từ thư mục scripts/ lẫn từ backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS = "  [OK]  "
FAIL = "  [LOI]"

_results: list[tuple[bool, str, str]] = []


def check(name: str):
    """Decorator biến 1 hàm thành một mục kiểm tra, nuốt lỗi để chạy hết các mục."""

    def wrapper(fn):
        try:
            fn()
            _results.append((True, name, ""))
            print(f"{PASS} {name}")
        except Exception as e:
            detail = f"{type(e).__name__}: {e}"
            _results.append((False, name, detail))
            print(f"{FAIL} {name}\n         {detail}")
            if os.getenv("CHECK_NEON_TRACE"):
                traceback.print_exc()
        return fn

    return wrapper


def main() -> int:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        print("Chua co DATABASE_URL. Dat bien moi truong roi chay lai.")
        print("Vi du: postgresql://user:pass@ep-xxx-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require")
        return 2
    if not url.startswith("postgres"):
        print(f"DATABASE_URL khong phai Postgres: {url[:40]}...")
        return 2

    # Neon dùng nhiều worker -> phải là chuỗi pooled, nếu không sẽ "too many connections".
    if "-pooler" not in url:
        print("  [CANH BAO] Chuoi ket noi khong co '-pooler'.")
        print("             Neon co gioi han connection; dung Pooled connection string.")

    import storage_service as storage

    if not storage.USE_POSTGRES:
        print("storage_service khong nhan dien Postgres (psycopg chua cai?).")
        print("Chay: pip install -r requirements.txt")
        return 2

    host = url.split("@")[-1].split("/")[0]
    print(f"\nKet noi: {host}\n")

    @check("Tao schema + ket noi pool")
    def _schema():
        storage._init_schema_once()

    @check("Portfolio: doc trang thai ban dau")
    def _portfolio_read():
        portfolio = storage.get_portfolio()
        assert "cash" in portfolio, portfolio
        assert isinstance(portfolio.get("holdings"), list)

    @check("Portfolio: mua -> ban (RETURNING id + lot FIFO)")
    def _portfolio_trade():
        storage.reset_portfolio()
        bought = storage.record_buy("FPT", 100, 70000.0, "CHECK")
        assert bought["ok"], bought
        # t_plus_lock_ms=0 de khong phai cho T+2
        sold = storage.record_sell("FPT", 100, 72000.0, "CHECK", t_plus_lock_ms=0)
        assert sold["ok"], sold
        assert len(storage.get_transactions(limit=10)) >= 2
        storage.reset_portfolio()

    @check("Alert: them / loc theo ma / danh dau / xoa (BOOLEAN)")
    def _alerts():
        rule_id = str(uuid.uuid4())
        storage.insert_alert_rule(
            {
                "id": rule_id,
                "symbol": "ZZZ",
                "condition": "price_above",
                "threshold": 1.0,
                "created_at": 1,
                "triggered_at": None,
            }
        )
        rows = storage.list_alert_rules("ZZZ")
        assert rows and rows[0]["id"] == rule_id, rows
        # Day la cho SQLite (0/1) va Postgres (boolean) de lech nhau nhat.
        assert rows[0]["active"] is True, f"active phai la True, nhan duoc {rows[0]['active']!r}"

        storage.mark_alert_rule_triggered(rule_id, 2)
        after = storage.list_alert_rules("ZZZ")[0]
        assert after["active"] is False, f"sau khi trigger active phai False, nhan {after['active']!r}"
        assert after["triggered_at"] == 2

        assert storage.delete_alert_rule(rule_id) is True
        assert storage.delete_alert_rule(rule_id) is False, "xoa lan 2 phai tra False"

    @check("AI signal: upsert (ON CONFLICT) + hang doi pending")
    def _ai_signal():
        storage.set_ai_signal("ZZZ", "BUY")
        assert storage.get_ai_signals().get("ZZZ") == "BUY"
        storage.set_ai_signal("ZZZ", "SELL")  # upsert, khong duoc raise duplicate key
        assert storage.get_ai_signals().get("ZZZ") == "SELL"

        storage.mark_ai_signal_pending("ZZZ")
        storage.mark_ai_signal_pending("ZZZ")  # goi 2 lan phai idempotent
        pending = storage.take_ai_signal_pending()
        assert "ZZZ" in pending, pending
        assert storage.take_ai_signal_pending() == [], "pending phai rong sau khi lay"

    @check("Giao dich that: ghi / chong trung theo ext_id / xoa")
    def _real_txn():
        ext_id = f"check-{uuid.uuid4()}"
        record = {
            "id": str(uuid.uuid4()),
            "ext_id": ext_id,
            "date": "2026-01-02",
            "symbol": "ZZZ",
            "side": "BUY",
            "quantity": 100,
            "price": 10000.0,
            "fee": 15.0,
            "tax": 0.0,
            "note": "check_neon",
            "source": "check",
        }
        first = storage.insert_real_transactions([record])
        assert first["inserted"] == 1, first

        # Cung ext_id -> phai bi bo qua, khong duoc raise unique violation.
        again = storage.insert_real_transactions([{**record, "id": str(uuid.uuid4())}])
        assert again["inserted"] == 0 and again["skipped"] == 1, again

        rows = storage.list_real_transactions("ZZZ")
        assert rows and rows[0]["quantity"] == 100
        assert isinstance(rows[0]["fee"], float), type(rows[0]["fee"])

        assert storage.delete_real_transaction(record["id"]) is True
        assert storage.list_real_transactions("ZZZ") == []

    @check("Rollback: transaction hong khong duoc ghi mot phan")
    def _rollback():
        good = {
            "id": str(uuid.uuid4()),
            "ext_id": f"check-rb-{uuid.uuid4()}",
            "date": "2026-01-03",
            "symbol": "ZZZ",
            "side": "BUY",
            "quantity": 1,
            "price": 1.0,
            "fee": 0.0,
            "tax": 0.0,
            "note": "",
            "source": "check",
        }
        bad = {**good, "id": str(uuid.uuid4()), "ext_id": None, "quantity": "khong-phai-so"}
        try:
            storage.insert_real_transactions([good, bad])
        except Exception:
            pass
        leftover = [t for t in storage.list_real_transactions("ZZZ") if t["ext_id"] == good["ext_id"]]
        assert leftover == [], "dong hop le van bi ghi du transaction that bai -> rollback khong hoat dong"

    # Don sach du lieu test con sot.
    try:
        for txn in storage.list_real_transactions("ZZZ"):
            storage.delete_real_transaction(txn["id"])
        for rule in storage.list_alert_rules("ZZZ"):
            storage.delete_alert_rule(rule["id"])
    except Exception as e:
        print(f"  [CANH BAO] Khong don sach duoc du lieu test: {e}")

    failed = [r for r in _results if not r[0]]
    print(f"\n{'-' * 58}")
    if failed:
        print(f"KET QUA: {len(_results) - len(failed)}/{len(_results)} muc dat. CHUA nen deploy.")
        for _, name, detail in failed:
            print(f"  - {name}: {detail}")
        print("\nChay lai voi CHECK_NEON_TRACE=1 de xem stack trace day du.")
        return 1

    print(f"KET QUA: {len(_results)}/{len(_results)} muc dat. Neon san sang.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
