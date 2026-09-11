"""
Job tìm mã đáng mua toàn thị trường (jobs/verdict_scan.py) và bảng lưu verdict_scan.

Không gọi mạng: verdict_for, danh sách niêm yết, bảng giá, danh mục, VN100 và bản đồ
ngành đều được thay bằng hàm giả. DB là SQLite tạm qua fixture temp_storage.
"""
from __future__ import annotations

import importlib

import pytest

from verdict_engine import LABELS


@pytest.fixture()
def vs(temp_storage, monkeypatch):
    import jobs.verdict_scan as module

    module = importlib.reload(module)
    monkeypatch.setattr(module, "BOARD_PAUSE_SECONDS", 0)
    return module


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


def _stub_sources(vs, monkeypatch, held=(), vn100=("FPT", "HPG", "VNM", "ACB")):
    monkeypatch.setattr(
        "real_portfolio_service.get_real_portfolio",
        lambda include_prices=True: {"positions": [{"symbol": s} for s in held]},
    )
    monkeypatch.setattr("sector_service.get_vn100_symbols", lambda: list(vn100))
    monkeypatch.setattr(vs, "_industry_map", lambda: {"FPT": "Công nghệ Thông tin", "SHS": "Dịch vụ tài chính"})


class TestChonMa:
    def test_ma_dang_giu_roi_ma_canh_bao_roi_vn100(self, vs, monkeypatch):
        _stub_sources(vs, monkeypatch, held=["HPG"])
        monkeypatch.setattr(
            vs.storage,
            "list_alert_rules",
            lambda: [{"symbol": "VNM", "active": True}, {"symbol": "SSI", "active": False}],
        )
        u = vs.pick_universe(market=False)
        assert u["symbols"] == ["HPG", "VNM", "FPT", "ACB"]
        assert u["held"] == ["HPG"]
        assert u["vn100"] == {"FPT", "HPG", "VNM", "ACB"}
        assert u["coverage"] == {"mode": "vn100", "priority": 4}
        assert u["meta"]["FPT"] == {"in_vn100": True, "industry": "Công nghệ Thông tin"}

    def test_chi_dinh_ma_thi_chi_quet_cac_ma_do(self, vs, monkeypatch):
        _stub_sources(vs, monkeypatch)
        assert vs.pick_universe([" fpt", "VNM", "FPT"])["symbols"] == ["FPT", "VNM"]

    def test_toan_thi_truong_loc_roi_noi_sau_vn100(self, vs, monkeypatch):
        _stub_sources(vs, monkeypatch)
        listed = {s: "HOSE" for s in ("FPT", "HPG", "VNM", "ACB", "NOT")}
        listed.update({"SHS": "HNX", "PVS": "HNX", "ABC": "UPCoM", "PEN": "HNX", "DEAD": "UPCoM", "LOST": "UPCoM"})
        board = {
            "FPT": {"price": 72_700.0, "value": 400e9},
            "HPG": {"price": 21_300.0, "value": 450e9},
            "VNM": {"price": 59_900.0, "value": 240e9},
            "ACB": {"price": 20_000.0, "value": 0.5e9},  # VN100 luôn được chấm dù hôm nay ít giao dịch
            "SHS": {"price": 14_300.0, "value": 3e9},
            "PVS": {"price": 38_400.0, "value": 200e9},
            "ABC": {"price": 12_000.0, "value": 1e9},
            "PEN": {"price": 5_000.0, "value": 9e9},
            "DEAD": {"price": 8_000.0, "value": 0.0},
        }
        seen = []
        monkeypatch.setattr(vs, "_listed_stocks", lambda: listed)
        monkeypatch.setattr(vs, "_price_board", lambda symbols: (seen.extend(symbols) or board, ["LOST"]))

        u = vs.pick_universe()
        # VN100 trước, rồi mã khác qua vòng lọc, giao dịch nhiều trước.
        assert u["symbols"] == ["FPT", "HPG", "VNM", "ACB", "PVS", "SHS"]
        assert sorted(seen) == sorted(listed)  # bảng giá lấy cho cả sàn trong một lượt
        c = u["coverage"]
        assert c["mode"] == "market" and c["listed"] == 11 and c["priority"] == 4
        assert c["prefilter_passed"] == 2 and c["excluded"] == 5
        assert (c["illiquid"], c["penny"], c["no_trade"], c["no_data"], c["board_failed"]) == (1, 1, 1, 1, 1)
        assert c["board_ok"] is True
        assert u["meta"]["SHS"] == {"exchange": "HNX", "value": 3e9, "in_vn100": False, "industry": "Dịch vụ tài chính"}
        assert set(u["meta"]) == set(u["symbols"])

    def test_bang_gia_hong_ca_san_thi_van_cham_vn100(self, vs, monkeypatch):
        _stub_sources(vs, monkeypatch)
        monkeypatch.setattr(vs, "_listed_stocks", lambda: {"FPT": "HOSE", "SHS": "HNX"})
        monkeypatch.setattr(vs, "_price_board", lambda symbols: ({}, list(symbols)))
        u = vs.pick_universe()
        assert u["symbols"] == ["FPT", "HPG", "VNM", "ACB"]
        assert u["coverage"]["board_ok"] is False and u["coverage"]["board_failed"] == 1


class TestVongLoc:
    def test_giu_ma_du_nguong_giao_dich_nhieu_truoc(self, vs):
        board = {
            "AAA": {"price": 20_000.0, "value": 3e9},
            "BBB": {"price": 20_000.0, "value": 30e9},
            "CCC": {"price": 20_000.0, "value": 1.9e9},
        }
        passed, stats = vs.prefilter(["AAA", "BBB", "CCC"], board, [], min_value=2e9, min_price=10_000)
        assert passed == ["BBB", "AAA"]
        assert stats["illiquid"] == 1

    def test_lo_loi_khong_bi_coi_la_khong_giao_dich(self, vs):
        passed, stats = vs.prefilter(["AAA"], {}, ["AAA"])
        assert passed == [] and stats["board_failed"] == 1 and stats["no_trade"] == 0

    def test_bang_gia_chia_lo_va_thu_lai(self, vs, monkeypatch):
        calls = []

        def fake_board(batch):
            calls.append(len(batch))
            if len(calls) == 1:
                return {}  # lô đầu lỗi lần một, thành công lần hai
            return {s: {"price": 10_000, "total_volume": 1_000} for s in batch}

        monkeypatch.setattr("foreign_service.fetch_price_board", fake_board)
        symbols = [f"A{i:02d}" for i in range(100)]
        board, failed = vs._price_board(symbols)
        assert calls == [80, 80, 20]
        assert failed == [] and len(board) == 100
        assert board["A00"] == {"price": 10_000.0, "value": 10_000_000.0}


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

    def test_nhip_quet_tinh_tu_luc_bat_dau_ma_truoc(self, vs, monkeypatch):
        clock = [0.0]
        sleeps = []
        monkeypatch.setattr(vs.time, "monotonic", lambda: clock[0])

        def fake_sleep(seconds):
            sleeps.append(seconds)
            clock[0] += seconds

        monkeypatch.setattr(vs.time, "sleep", fake_sleep)

        def fake(symbol):
            clock[0] += 3.0  # chính request mất 3 giây
            return _result(symbol)

        vs.scan(["A", "B", "C"], throttle=9.0, fetch=fake)
        assert sleeps == [6.0, 6.0]  # không nghỉ sau mã cuối

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
    def test_sap_xep_dem_danh_dau_va_gan_thong_tin_ma(self, vs):
        results = {
            "AAA": _row(vs, "AAA", "avoid", "same"),
            "BBB": _row(vs, "BBB", "buy_consider", "worse"),
            "CCC": _row(vs, "CCC", "buy_consider", "better"),
            "DDD": _row(vs, "DDD", "wait"),
        }
        meta = {"CCC": {"exchange": "HNX", "value": 3e9, "in_vn100": False, "industry": "Xây dựng"}}
        coverage = {"mode": "market", "listed": 1700}
        p = vs.build_payload(
            results, {"EEE": "lỗi"}, ["AAA"], "2026-09-11", "2026-09-11 15:52", meta=meta, coverage=coverage
        )
        assert [r["symbol"] for r in p["results"]] == ["CCC", "BBB", "DDD", "AAA"]
        assert p["counts"] == {"buy_consider": 2, "wait": 1, "avoid": 1}
        assert [r["symbol"] for r in p["results"] if r["held"]] == ["AAA"]
        assert p["results"][0]["exchange"] == "HNX" and p["results"][0]["industry"] == "Xây dựng"
        assert p["coverage"] == coverage and p["universe"] == "market"
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
        picks = []

        def fake_pick(explicit=None, market=True):
            picks.append(market)
            return {
                "symbols": list(explicit) if explicit else ["FPT", "HPG", "VNM", "ACB"],
                "held": ["FPT"],
                "vn100": set(),
                "sector_of": {},
                "meta": {"HPG": {"exchange": "HOSE", "in_vn100": True}},
                "coverage": {"mode": "market" if market else "vn100"},
            }

        monkeypatch.setattr(vs, "pick_universe", fake_pick)
        monkeypatch.setattr(vs, "_today", lambda: "2026-09-11")
        monkeypatch.setattr(vs, "RETRY_PAUSE_SECONDS", 0)
        vs.picks = picks
        return vs

    def _stub_scan(self, vs, monkeypatch, fail=()):
        calls = []

        def fake(symbols, throttle=0, vn100=None, fetch=None, sector_of=None):
            calls.append(list(symbols))
            ok = {s: _row(vs, s, "buy_consider") for s in symbols if s not in fail}
            return ok, {s: "lỗi" for s in symbols if s in fail}

        monkeypatch.setattr(vs, "scan", fake)
        return calls

    def test_luot_toan_thi_truong_duoc_ghi(self, job, monkeypatch):
        self._stub_scan(job, monkeypatch)
        assert job.main([]) == 0
        assert job.picks == [True]
        saved = job.storage.get_verdict_scan("2026-09-11")
        assert saved["counts"]["buy_consider"] == 4
        assert saved["coverage"] == {"mode": "market"}
        assert [r["symbol"] for r in saved["results"] if r["held"]] == ["FPT"]
        assert next(r for r in saved["results"] if r["symbol"] == "HPG")["exchange"] == "HOSE"

    def test_chon_chi_vn100(self, job, monkeypatch):
        self._stub_scan(job, monkeypatch)
        assert job.main(["--universe", "vn100"]) == 0
        assert job.picks == [False]

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
