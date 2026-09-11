"""
Job quét kết luận cả rổ (jobs/verdict_scan.py) và bảng lưu verdict_scan.

Không gọi mạng: verdict_for, danh mục và VN100 đều được thay bằng hàm giả. DB là
SQLite tạm qua fixture temp_storage.
"""
from __future__ import annotations

import importlib

import pytest

from verdict_engine import LABELS


@pytest.fixture()
def vs(temp_storage):
    import jobs.verdict_scan as module

    return importlib.reload(module)


def _result(symbol, verdict="wait", edge=None, gaps=None):
    """Kết quả dạng verdict_for trả về, rút gọn đủ cho job."""
    return {
        "symbol": symbol,
        "price": 10_000.0,
        "verdict": verdict,
        "label": LABELS[verdict],
        "headline": "lý do",
        "sector": None,
        "checks": [
            {"label": "Bộ lọc an toàn", "status": "pass"},
            {"label": "Giá trên đường EMA200", "status": "fail"},
        ],
        "history": {"edge": edge, "hit_ratio": 0.6, "baseline_hit_ratio": 0.5, "samples": 120},
        "data_gaps": gaps or [],
    }


def _row(vs, symbol, verdict="wait", edge=None, gaps=None):
    return vs.summarize(_result(symbol, verdict, edge, gaps))


def _stub_universe(monkeypatch, held=(), vn100=("FPT", "HPG", "VNM", "ACB")):
    monkeypatch.setattr(
        "real_portfolio_service.get_real_portfolio",
        lambda include_prices=True: {"positions": [{"symbol": s} for s in held]},
    )
    monkeypatch.setattr("sector_service.get_vn100_symbols", lambda: list(vn100))


class TestChonMa:
    def test_ma_dang_giu_roi_ma_canh_bao_roi_vn100(self, vs, monkeypatch):
        _stub_universe(monkeypatch, held=["HPG"])
        monkeypatch.setattr(
            vs.storage,
            "list_alert_rules",
            lambda: [{"symbol": "VNM", "active": True}, {"symbol": "SSI", "active": False}],
        )
        u = vs.pick_universe()
        assert u["symbols"] == ["HPG", "VNM", "FPT", "ACB"]
        assert u["held"] == ["HPG"]
        assert u["vn100"] == {"FPT", "HPG", "VNM", "ACB"}

    def test_chi_dinh_ma_thi_chi_quet_cac_ma_do(self, vs, monkeypatch):
        _stub_universe(monkeypatch)
        assert vs.pick_universe([" fpt", "VNM", "FPT"])["symbols"] == ["FPT", "VNM"]


class TestQuet:
    def test_ma_loi_khong_lam_hong_ca_luot(self, vs):
        def fake(symbol):
            if symbol == "BAD":
                raise RuntimeError("Không lấy được dữ liệu giá của BAD.")
            if symbol == "EXIT":
                raise SystemExit(1)  # vnstock từng sys.exit khi dính hạn mức
            return _result(symbol, "buy_consider", "better")

        results, errors = vs.scan(["FPT", "BAD", "EXIT", "VNM"], throttle=0, fetch=fake)
        assert list(results) == ["FPT", "VNM"]
        assert set(errors) == {"BAD", "EXIT"}
        assert results["FPT"]["failed"] == ["Giá trên đường EMA200"]
        assert results["FPT"]["edge"] == "better"

    def test_thu_lai_thanh_cong_thi_thay_loi(self, vs):
        results = {"FPT": _row(vs, "FPT", gaps=["thiếu"])}
        errors = {"BAD": "lỗi"}
        vs.merge_retry(results, errors, {"BAD": _row(vs, "BAD", "avoid")}, {"FPT": "lỗi lần 2"})
        assert errors == {}
        assert results["BAD"]["verdict"] == "avoid"
        # Lượt thử lại lỗi thì giữ kết quả lần đầu, dù thiếu dữ liệu.
        assert results["FPT"]["data_gaps"] == ["thiếu"]

    def test_quet_duoc_it_hon_nua_la_hong(self, vs):
        assert vs.is_healthy(5, 10)
        assert not vs.is_healthy(4, 10)
        assert not vs.is_healthy(0, 0)


class TestGoiKetQua:
    def test_sap_xep_dem_va_danh_dau_ma_dang_giu(self, vs):
        results = {
            "AAA": _row(vs, "AAA", "avoid", "same"),
            "BBB": _row(vs, "BBB", "buy_consider", "worse"),
            "CCC": _row(vs, "CCC", "buy_consider", "better"),
            "DDD": _row(vs, "DDD", "wait"),
        }
        p = vs.build_payload(results, {"EEE": "lỗi"}, ["AAA"], "2026-09-11", "2026-09-11 15:52")
        assert [r["symbol"] for r in p["results"]] == ["CCC", "BBB", "DDD", "AAA"]
        assert p["counts"] == {"buy_consider": 2, "wait": 1, "avoid": 1}
        assert [r["symbol"] for r in p["results"] if r["held"]] == ["AAA"]
        assert p["errors"] == [{"symbol": "EEE", "error": "lỗi"}]
        assert p["changes"] == [] and p["previous_date"] is None
        assert "EMA200" in p["rule"] and "không phải lời khuyên" in p["disclaimer"]

    def test_ma_doi_ket_luan_so_voi_luot_truoc(self, vs):
        previous = {
            "scan_date": "2026-09-10",
            "results": [
                {"symbol": "FPT", "verdict": "avoid"},
                {"symbol": "HPG", "verdict": "wait"},
                {"symbol": "VNM", "verdict": "wait"},
            ],
        }
        results = {
            "FPT": _row(vs, "FPT", "wait"),
            "HPG": _row(vs, "HPG", "buy_consider"),
            "VNM": _row(vs, "VNM", "wait"),
            "ACB": _row(vs, "ACB", "buy_consider"),  # mã mới, không có mốc để so
        }
        p = vs.build_payload(results, {}, ["FPT"], "2026-09-11", "t", previous)
        assert p["previous_date"] == "2026-09-10"
        # Mã đang giữ lên đầu dù đổi sang kết luận xếp sau.
        assert [(c["symbol"], c["from"], c["to"]) for c in p["changes"]] == [
            ("FPT", "avoid", "wait"),
            ("HPG", "wait", "buy_consider"),
        ]
        assert p["changes"][1]["to_label"] == "Có thể cân nhắc mua"


class TestLuuTru:
    def test_luu_doc_va_tim_luot_truoc(self, vs):
        storage = vs.storage
        assert storage.get_verdict_scan() is None
        storage.save_verdict_scan("2026-09-10", {"date": "2026-09-10", "results": [1]})
        storage.save_verdict_scan("2026-09-11", {"date": "2026-09-11", "results": [2]})
        storage.save_verdict_scan("2026-09-11", {"date": "2026-09-11", "results": [3]})  # chạy lại trong ngày

        latest = storage.get_verdict_scan()
        assert latest["scan_date"] == "2026-09-11" and latest["results"] == [3]
        assert storage.get_verdict_scan("2026-09-10")["results"] == [1]
        assert storage.get_previous_verdict_scan("2026-09-11")["scan_date"] == "2026-09-10"
        assert storage.get_previous_verdict_scan("2026-09-10") is None
        assert storage.list_verdict_scan_dates() == ["2026-09-11", "2026-09-10"]


class TestChayJob:
    @pytest.fixture()
    def job(self, vs, monkeypatch):
        """Job với rổ 4 mã và kết quả giả; ngày quét cố định."""
        monkeypatch.setattr(
            vs,
            "pick_universe",
            lambda explicit=None: {
                "symbols": list(explicit) if explicit else ["FPT", "HPG", "VNM", "ACB"],
                "held": ["FPT"],
                "vn100": set(),
            },
        )
        monkeypatch.setattr(vs, "_today", lambda: "2026-09-11")
        monkeypatch.setattr(vs, "RETRY_PAUSE_SECONDS", 0)
        return vs

    def _stub_scan(self, vs, monkeypatch, fail=()):
        calls = []

        def fake(symbols, throttle=0, vn100=None, fetch=None):
            calls.append(list(symbols))
            ok = {s: _row(vs, s, "buy_consider") for s in symbols if s not in fail}
            return ok, {s: "lỗi" for s in symbols if s in fail}

        monkeypatch.setattr(vs, "scan", fake)
        return calls

    def test_luot_du_ro_duoc_ghi(self, job, monkeypatch):
        self._stub_scan(job, monkeypatch)
        assert job.main([]) == 0
        saved = job.storage.get_verdict_scan("2026-09-11")
        assert saved["counts"]["buy_consider"] == 4
        assert [r["symbol"] for r in saved["results"] if r["held"]] == ["FPT"]

    def test_luot_quet_thu_khong_ghi(self, job, monkeypatch):
        self._stub_scan(job, monkeypatch)
        assert job.main(["--symbols", "FPT"]) == 0
        assert job.main(["--limit", "2"]) == 0
        assert job.main(["--dry-run"]) == 0
        assert job.storage.get_verdict_scan() is None

    def test_luot_hong_khong_de_luot_cu(self, job, monkeypatch):
        job.storage.save_verdict_scan("2026-09-11", {"date": "2026-09-11", "results": ["cũ"]})
        calls = self._stub_scan(job, monkeypatch, fail={"HPG", "VNM", "ACB"})
        assert job.main([]) == 1
        assert job.storage.get_verdict_scan()["results"] == ["cũ"]
        # Mã lỗi được thử lại một lần.
        assert calls == [["FPT", "HPG", "VNM", "ACB"], ["HPG", "VNM", "ACB"]]
