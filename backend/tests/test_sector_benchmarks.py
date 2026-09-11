"""
Chọn mã đại diện ngành cho bảng trung vị.

Khoá lại lỗi đã xảy ra thật: price_board dính rate limit, trả dict rỗng, và job
lấp chỗ trống theo thứ tự ABC — ngành Hàng cá nhân & Gia dụng thành A32, AAT,
ADS, BBT... thay vì PNJ, TCM, TNG. Không test nào gọi mạng: danh sách ngành và
bảng giá đều được thay bằng dữ liệu giả.
"""
from __future__ import annotations

import pytest

import jobs.sector_benchmarks as sb


@pytest.fixture(autouse=True)
def _khong_ngu(monkeypatch):
    monkeypatch.setattr(sb.time, "sleep", lambda s: None)


def _industries(monkeypatch, sectors):
    monkeypatch.setattr(
        sb,
        "get_industries",
        lambda: [{"name": name, "symbols": syms} for name, syms in sectors.items()],
    )


class TestPickUniverse:
    def test_ma_khong_giao_dich_bi_loai_khong_lap_theo_abc(self, monkeypatch):
        _industries(monkeypatch, {"Gia dung": ["A32", "AAT", "ADS", "BBT", "PNJ", "TCM", "TNG"]})
        monkeypatch.setattr(
            sb,
            "_liquidity_rank",
            lambda m: {"PNJ": 9e9, "TCM": 5e9, "TNG": 1e9, "A32": 0.0, "AAT": 0.0},
        )
        # Còn 9 suất trống nhưng không được lấp bằng A32, AAT, ADS, BBT.
        assert sb.pick_universe(per_sector=12, core=[]) == ["PNJ", "TCM", "TNG"]

    def test_vn100_luon_dung_truoc(self, monkeypatch):
        _industries(monkeypatch, {"Ngan hang": ["ACB", "XYZ", "VCB"]})
        monkeypatch.setattr(sb, "_liquidity_rank", lambda m: {"XYZ": 9e12, "ACB": 1e9, "VCB": 2e9})
        chosen = sb.pick_universe(per_sector=2, core=["ACB", "VCB"])
        assert chosen == ["VCB", "ACB"]

    def test_khong_xep_hang_duoc_thi_chi_dung_vn100(self, monkeypatch, capsys):
        _industries(monkeypatch, {"Du lich": ["ATS", "BCV", "BLN", "VJC", "HVN"]})
        monkeypatch.setattr(sb, "_liquidity_rank", lambda m: None)
        assert sb.pick_universe(per_sector=12, core=["VJC"]) == ["VJC"]
        # Phải kêu to — bản cũ im lặng nên bảng sai đi thẳng vào commit.
        assert "CANH BAO" in capsys.readouterr().out

    def test_ma_vn100_khong_giao_dich_van_giu(self, monkeypatch):
        # Mã trong rổ chính là mã người dùng tra cứu nhiều nhất; một phiên tạm
        # ngừng giao dịch không được làm nó biến mất khỏi bảng.
        _industries(monkeypatch, {"X": ["AAA", "FPT"]})
        monkeypatch.setattr(sb, "_liquidity_rank", lambda m: {"AAA": 0.0, "FPT": 0.0})
        assert sb.pick_universe(per_sector=12, core=["FPT"]) == ["FPT"]


class TestLiquidityRank:
    def _board(self, monkeypatch, responses):
        import foreign_service

        calls = []

        def fake(batch):
            calls.append(list(batch))
            return responses.pop(0) if responses else {}

        monkeypatch.setattr(foreign_service, "fetch_price_board", fake)
        return calls

    def test_thu_lai_khi_bang_gia_rong(self, monkeypatch):
        calls = self._board(monkeypatch, [{}, {"FPT": {"price": 70000, "total_volume": 1000}}])
        assert sb._liquidity_rank(["FPT"]) == {"FPT": 70000.0 * 1000}
        assert len(calls) == 2

    def test_that_bai_het_so_lan_thu_thi_tra_none(self, monkeypatch):
        # None, không phải {}: dict rỗng sẽ bị hiểu thành "mọi mã thanh khoản 0".
        calls = self._board(monkeypatch, [])
        assert sb._liquidity_rank(["FPT", "HPG"], retries=3) is None
        assert len(calls) == 3

    def test_mot_lo_hong_la_ca_nganh_none(self, monkeypatch):
        # 81 mã = 2 lô, lô hai hỏng. Thứ hạng thiếu một nửa nguy hiểm hơn việc báo
        # thẳng là không xếp hạng được.
        syms = [f"A{i:02d}" for i in range(81)]
        ok = {s: {"price": 1, "total_volume": 1} for s in syms[:80]}
        self._board(monkeypatch, [ok])
        assert sb._liquidity_rank(syms, retries=2) is None

    def test_nghi_ca_truoc_lo_dau_tien(self, monkeypatch):
        # Bản cũ bỏ qua lô đầu nên đầu mỗi ngành bắn liền nhau -> dính rate limit.
        slept = []
        monkeypatch.setattr(sb.time, "sleep", lambda s: slept.append(s))
        self._board(monkeypatch, [{"FPT": {"price": 1, "total_volume": 1}}])
        sb._liquidity_rank(["FPT"])
        assert slept == [3.0]
