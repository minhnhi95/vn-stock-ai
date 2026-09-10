"""
Tính lãi/lỗ danh mục thật — FIFO + phí + thuế.

Đây là code "tiền thật" của app: sai ở đây thì người dùng ra quyết định bán/giữ
dựa trên con số sai. Test bám vào các con số tính tay được, không mock.

Không gọi mạng: `include_prices=False` cho phần vị thế, và monkeypatch giá khi
cần kiểm tra lãi/lỗ chưa thực hiện.
"""
from __future__ import annotations

import importlib

import pytest

from broker_import_service import build_manual_record


@pytest.fixture()
def real(temp_storage):
    """real_portfolio_service trỏ vào DB tạm của temp_storage."""
    import real_portfolio_service

    return importlib.reload(real_portfolio_service)


def _add(storage, date, symbol, side, qty, price, fee=0.0, tax=0.0):
    record = build_manual_record(date, symbol, side, qty, price, fee=fee, tax=tax)
    storage.insert_real_transactions([record])
    return record


class TestEmpty:
    def test_chua_co_giao_dich(self, real):
        result = real.get_real_portfolio(include_prices=False)
        assert result["empty"] is True
        assert result["positions"] == []


class TestCostBasis:
    def test_phi_mua_duoc_gop_vao_gia_von(self, real, temp_storage):
        # 1000 CP giá 68.500 + phí 102.750 -> giá vốn mỗi CP = 68.602,75
        _add(temp_storage, "2026-03-05", "FPT", "BUY", 1000, 68500, fee=102750)
        position = real.get_real_portfolio(include_prices=False)["positions"][0]
        assert position["avg_cost"] == pytest.approx(68602.75)
        assert position["cost_basis"] == pytest.approx(68602750, abs=1)

    def test_nhieu_lo_mua_gop_dung(self, real, temp_storage):
        _add(temp_storage, "2026-03-05", "FPT", "BUY", 1000, 68500, fee=102750)
        _add(temp_storage, "2026-05-12", "FPT", "BUY", 500, 71200, fee=53400)
        position = real.get_real_portfolio(include_prices=False)["positions"][0]
        assert position["shares"] == 1500
        assert len(position["lots"]) == 2


class TestFifo:
    @pytest.fixture()
    def fpt_history(self, temp_storage):
        # Mua 1000@68.500 (phí 102.750), mua 500@71.200 (phí 53.400),
        # bán 800@79.000 (phí 94.800, thuế 63.200).
        _add(temp_storage, "2026-03-05", "FPT", "BUY", 1000, 68500, fee=102750)
        _add(temp_storage, "2026-05-12", "FPT", "BUY", 500, 71200, fee=53400)
        _add(temp_storage, "2026-07-15", "FPT", "SELL", 800, 79000, fee=94800, tax=63200)

    def test_ban_khop_vao_lo_mua_cu_nhat(self, real, temp_storage, fpt_history):
        # FIFO: 800 CP lấy từ lô đầu (giá vốn 68.602,75), không phải bình quân.
        # Giá vốn khớp = 800 x 68.602,75 = 54.882.200
        # Tiền về      = 800 x 79.000 - 94.800 - 63.200 = 63.042.000
        # Lãi          = 8.159.800
        realized = real.get_real_portfolio(include_prices=False)["realized_by_symbol"]
        assert realized[0]["symbol"] == "FPT"
        assert realized[0]["pnl"] == pytest.approx(8159800, abs=1)

    def test_gia_von_con_lai_sau_ban(self, real, temp_storage, fpt_history):
        # Còn 200 CP của lô 1 + 500 CP của lô 2
        # = 200 x 68.602,75 + 500 x 71.306,80 = 49.373.950 -> 70.534,21/CP
        position = real.get_real_portfolio(include_prices=False)["positions"][0]
        assert position["shares"] == 700
        assert position["avg_cost"] == pytest.approx(70534.21, abs=0.05)

    def test_ban_het_thi_khong_con_vi_the(self, real, temp_storage):
        _add(temp_storage, "2026-03-05", "HPG", "BUY", 2000, 24300, fee=72900)
        _add(temp_storage, "2026-08-28", "HPG", "SELL", 2000, 22100, fee=66300, tax=44200)
        result = real.get_real_portfolio(include_prices=False)
        assert result["positions"] == []
        assert result["realized_by_symbol"][0]["pnl"] == pytest.approx(-4583400, abs=1)


class TestThueVaPhi:
    def test_thue_ban_lam_giam_tien_ve(self, real, temp_storage):
        """
        Mua và bán CÙNG giá thì phải LỖ đúng bằng phí + thuế — đây chính là chỗ
        bảng Excel tự làm hay tính thành hoà vốn.
        """
        _add(temp_storage, "2026-03-05", "VNM", "BUY", 1000, 60000, fee=90000)
        _add(temp_storage, "2026-04-05", "VNM", "SELL", 1000, 60000, fee=90000, tax=60000)

        realized = real.get_real_portfolio(include_prices=False)["realized_by_symbol"][0]
        assert realized["pnl"] == pytest.approx(-(90000 + 90000 + 60000), abs=1)

    def test_tong_phi_thue_duoc_cong_don(self, real, temp_storage):
        _add(temp_storage, "2026-03-05", "VNM", "BUY", 1000, 60000, fee=90000)
        _add(temp_storage, "2026-04-05", "VNM", "SELL", 1000, 62000, fee=93000, tax=62000)
        summary = real.get_real_portfolio(include_prices=False)["summary"]
        assert summary["total_fees"] == pytest.approx(183000, abs=1)
        assert summary["total_taxes"] == pytest.approx(62000, abs=1)
        assert summary["cost_drag"] == pytest.approx(245000, abs=1)


class TestUnrealized:
    @pytest.fixture()
    def priced(self, real, temp_storage, monkeypatch):
        _add(temp_storage, "2026-03-05", "FPT", "BUY", 1000, 68500, fee=102750)
        monkeypatch.setattr(real, "_fetch_prices", lambda symbols: {"FPT": 80000.0})
        return real.get_real_portfolio(include_prices=True)

    def test_tru_truoc_chi_phi_thoat_vi_the(self, priced):
        # Giá trị gộp 80.000.000; phí bán 0,15% + thuế 0,1% = 200.000
        # Lãi = 80.000.000 - 200.000 - 68.602.750 = 11.197.250
        position = priced["positions"][0]
        assert position["market_value"] == pytest.approx(80000000, abs=1)
        assert position["exit_costs"] == pytest.approx(200000, abs=1)
        assert position["unrealized_pnl"] == pytest.approx(11197250, abs=1)

    def test_lai_nho_hon_chenh_lech_gia_don_thuan(self, priced):
        naive = (80000 - 68500) * 1000  # cách tính "thô" mà bảng Excel hay dùng
        assert priced["positions"][0]["unrealized_pnl"] < naive

    def test_ty_trong_duoc_tinh(self, priced):
        assert priced["positions"][0]["weight_pct"] == pytest.approx(100.0)


class TestWarnings:
    def test_canh_bao_tap_trung(self, real, temp_storage, monkeypatch):
        _add(temp_storage, "2026-03-05", "FPT", "BUY", 1000, 70000)
        _add(temp_storage, "2026-03-05", "HPG", "BUY", 100, 20000)
        monkeypatch.setattr(real, "_fetch_prices", lambda s: {"FPT": 70000.0, "HPG": 20000.0})
        warnings = real.get_real_portfolio(include_prices=True)["warnings"]
        assert any("FPT" in w and "%" in w for w in warnings)

    def test_ban_nhieu_hon_so_dang_co_thi_canh_bao(self, real, temp_storage):
        # Sổ thiếu lệnh mua cũ -> phải nói rõ thay vì âm thầm tính sai giá vốn.
        _add(temp_storage, "2026-03-05", "FPT", "BUY", 100, 70000)
        _add(temp_storage, "2026-04-05", "FPT", "SELL", 500, 75000)
        warnings = real.get_real_portfolio(include_prices=False)["warnings"]
        assert any("thiếu giao dịch mua" in w for w in warnings)


class TestTradingStats:
    @pytest.fixture()
    def history(self, temp_storage):
        _add(temp_storage, "2026-03-05", "FPT", "BUY", 1000, 68500, fee=102750)
        _add(temp_storage, "2026-07-15", "FPT", "SELL", 1000, 79000, fee=118500, tax=79000)
        _add(temp_storage, "2026-03-05", "HPG", "BUY", 2000, 24300, fee=72900)
        _add(temp_storage, "2026-08-28", "HPG", "SELL", 2000, 22100, fee=66300, tax=44200)

    def test_dem_lenh_va_ty_le_thang(self, real, history):
        stats = real.get_trading_stats()
        assert stats["buy_count"] == 2
        assert stats["sell_count"] == 2
        assert stats["symbols_closed"] == 2
        assert stats["win_rate_pct"] == 50.0

    def test_ty_le_chi_phi_tren_lai_gop(self, real, history):
        stats = real.get_trading_stats()
        assert stats["total_costs"] == pytest.approx(483650, abs=1)
        # Chỉ số này là thứ người dùng kiểm soát được, khác với hướng thị trường.
        assert stats["cost_vs_gross_profit_pct"] is not None

    def test_loc_theo_nam(self, real, history):
        assert real.get_trading_stats(year=2020)["empty"] is True
        assert real.get_trading_stats(year=2026)["empty"] is False


class TestPromptFormat:
    def test_tom_tat_co_du_so_lieu_chinh(self, real, temp_storage, monkeypatch):
        _add(temp_storage, "2026-03-05", "FPT", "BUY", 1000, 68500, fee=102750)
        monkeypatch.setattr(real, "_fetch_prices", lambda s: {"FPT": 80000.0})
        text = real.format_real_portfolio_for_prompt(real.get_real_portfolio(True))
        assert "FPT" in text
        assert "Phí + thuế" in text

    def test_danh_muc_rong(self, real):
        text = real.format_real_portfolio_for_prompt({"empty": True})
        assert "chưa có dữ liệu" in text.lower()
