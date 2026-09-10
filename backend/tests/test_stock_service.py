"""Chỉ báo kỹ thuật + chuẩn hoá dữ liệu biểu đồ (không chạm mạng)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from stock_service import (
    _trim_to_period,
    calculate_rsi,
    clean_symbol,
    format_chart_data,
    is_vn_stock,
    nan_safe_float,
)


class TestIsVnStock:
    # Ma VN duoc phep chua so (HT1 = Ha Tien 1, PC1, NT2...).
    @pytest.mark.parametrize("symbol", ["FPT", "HPG", "VNM", "HT1", "PC1"])
    def test_ma_hop_le(self, symbol):
        assert is_vn_stock(symbol) is True

    @pytest.mark.parametrize("symbol", ["FP", "FPTX", "AAPL", "", "FPT.VN", "1PT"])
    def test_ma_khong_hop_le(self, symbol):
        assert is_vn_stock(symbol) is False

    def test_clean_symbol_chuan_hoa(self):
        assert clean_symbol("  fpt ") == "FPT"


class TestNanSafeFloat:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (1.5, 1.5),
            (0, 0.0),
            (np.float64(2.5), 2.5),
            (float("nan"), None),
            (np.nan, None),
            (None, None),
            ("khong-phai-so", None),
        ],
    )
    def test_chuyen_doi(self, value, expected):
        assert nan_safe_float(value) == expected


class TestCalculateRsi:
    def test_gia_tang_lien_tuc_rsi_gan_100(self):
        series = pd.Series(range(1, 60), dtype=float)
        rsi = calculate_rsi(series, 14)
        assert rsi.iloc[-1] > 99

    def test_gia_giam_lien_tuc_rsi_gan_0(self):
        series = pd.Series(range(60, 1, -1), dtype=float)
        rsi = calculate_rsi(series, 14)
        assert rsi.iloc[-1] < 1

    def test_rsi_luon_trong_khoang_0_100(self):
        rng = np.random.default_rng(42)
        series = pd.Series(100 + rng.standard_normal(200).cumsum())
        rsi = calculate_rsi(series, 14).dropna()
        assert ((rsi >= 0) & (rsi <= 100)).all()


class TestFormatChartData:
    @pytest.fixture()
    def df(self):
        index = pd.date_range("2026-01-01", periods=3, freq="D")
        frame = pd.DataFrame(
            {
                "Open": [10.0, 11.0, 12.0],
                "High": [11.0, 12.0, 13.0],
                "Low": [9.0, 10.0, 11.0],
                "Close": [10.5, 11.5, 12.5],
                "Volume": [100, 200, 300],
                "EMA20": [np.nan, 11.0, 12.0],
                "EMA50": [np.nan, np.nan, 12.0],
                "EMA200": [np.nan, np.nan, np.nan],
                "RSI": [np.nan, 55.0, 60.0],
                "MACD": [0.1, 0.2, 0.3],
                "MACD_Signal": [0.1, 0.15, 0.2],
                "MACD_Hist": [0.0, 0.05, 0.1],
            },
            index=index,
        )
        return frame

    def test_chi_bao_chua_du_lieu_moi_tra_null(self, df):
        rows = format_chart_data(df)
        # NaN không phải JSON hợp lệ — phải là None để client hiểu "chưa có",
        # thay vì một con số bịa (bug cũ: RSI nến đầu = 99.99 do bfill).
        assert rows[0]["ema20"] is None
        assert rows[0]["rsi"] is None
        assert all(row["ema200"] is None for row in rows)

    def test_khong_con_nan_trong_output(self, df):
        rows = format_chart_data(df)
        floats = [v for row in rows for v in row.values() if isinstance(v, float)]
        assert not any(math.isnan(v) for v in floats)

    def test_gia_tri_hop_le_duoc_giu_nguyen(self, df):
        rows = format_chart_data(df)
        assert rows[-1]["close"] == 12.5
        assert rows[-1]["rsi"] == 60.0
        assert rows[-1]["volume"] == 300
        assert rows[0]["time"] == int(df.index[0].timestamp())


class TestTrimToPeriod:
    def test_cat_bo_phan_warmup(self):
        index = pd.date_range(end=pd.Timestamp.now().normalize(), periods=400, freq="D")
        df = pd.DataFrame({"Close": range(400)}, index=index)
        trimmed = _trim_to_period(df, days=90)
        assert len(trimmed) < len(df)
        assert (pd.Timestamp.now() - trimmed.index[0]).days <= 91

    def test_ma_moi_niem_yet_ngan_hon_khoang_yeu_cau_thi_giu_nguyen(self):
        index = pd.date_range(end=pd.Timestamp.now().normalize(), periods=5, freq="D")
        df = pd.DataFrame({"Close": range(5)}, index=index)
        assert len(_trim_to_period(df, days=365)) == 5

    def test_index_co_timezone_khong_loi(self):
        index = pd.date_range(end=pd.Timestamp.now(tz="UTC").normalize(), periods=100, freq="D", tz="UTC")
        df = pd.DataFrame({"Close": range(100)}, index=index)
        assert not _trim_to_period(df, days=30).empty
