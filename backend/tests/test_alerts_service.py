"""
Alert rules — CRUD và điều kiện kích hoạt.

Alerts lưu trong DB dùng chung với portfolio (trước đây là file JSON, hỏng khi
chạy nhiều gunicorn worker). Test chạy trên SQLite tạm qua fixture temp_storage.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
def alerts(temp_storage):
    """alerts_service trỏ vào cùng DB tạm với temp_storage."""
    import alerts_service

    return importlib.reload(alerts_service)


class TestCreateAlert:
    def test_tao_alert_hop_le(self, alerts):
        rule = alerts.create_alert("FPT", "price_above", 80000)
        assert rule["symbol"] == "FPT"
        assert rule["condition"] == "price_above"
        assert rule["threshold"] == 80000.0
        assert rule["active"] is True
        assert rule["triggered_at"] is None
        assert rule["id"]

    def test_symbol_duoc_chuan_hoa(self, alerts):
        assert alerts.create_alert("  fpt ", "price_above", 1)["symbol"] == "FPT"

    def test_symbol_rong_bi_tu_choi(self, alerts):
        with pytest.raises(ValueError, match="không được rỗng"):
            alerts.create_alert("", "price_above", 1)

    def test_dieu_kien_khong_hop_le_bi_tu_choi(self, alerts):
        with pytest.raises(ValueError, match="không hợp lệ"):
            alerts.create_alert("FPT", "gia_len_troi", 1)

    def test_threshold_khong_phai_so_bi_tu_choi(self, alerts):
        with pytest.raises(ValueError, match="phải là số"):
            alerts.create_alert("FPT", "price_above", "tám mươi nghìn")

    def test_threshold_none_thanh_0(self, alerts):
        # ai_signal_change không dùng threshold nên None là hợp lệ.
        assert alerts.create_alert("FPT", "ai_signal_change", None)["threshold"] == 0.0


class TestListAndDelete:
    def test_moi_nhat_len_dau(self, alerts):
        first = alerts.create_alert("FPT", "price_above", 1)
        second = alerts.create_alert("HPG", "price_below", 2)
        ids = [a["id"] for a in alerts.list_alerts()]
        # created_at cùng giây thì thứ tự có thể hoà — chỉ cần cả hai đều có mặt.
        assert set(ids) == {first["id"], second["id"]}

    def test_loc_theo_symbol(self, alerts):
        alerts.create_alert("FPT", "price_above", 1)
        alerts.create_alert("HPG", "price_below", 2)
        assert [a["symbol"] for a in alerts.list_alerts("FPT")] == ["FPT"]
        assert alerts.list_alerts("hpg")[0]["symbol"] == "HPG"

    def test_xoa_alert(self, alerts):
        rule = alerts.create_alert("FPT", "price_above", 1)
        assert alerts.delete_alert(rule["id"]) is True
        assert alerts.list_alerts() == []

    def test_xoa_id_khong_ton_tai_tra_false(self, alerts):
        assert alerts.delete_alert("khong-co-that") is False


class TestPersistence:
    def test_alert_song_sot_qua_reload_module(self, alerts):
        """
        Điểm mấu chốt của việc bỏ file JSON: state phải nằm ở DB, không phải
        biến in-memory của process — production chạy 2 gunicorn worker.
        """
        rule = alerts.create_alert("FPT", "price_above", 1)
        reloaded = importlib.reload(alerts)
        assert [a["id"] for a in reloaded.list_alerts()] == [rule["id"]]



class TestMarkTriggered:
    def test_danh_dau_da_kich_hoat(self, alerts):
        rule = alerts.create_alert("FPT", "price_above", 1)
        alerts.mark_triggered(rule["id"])

        stored = alerts.list_alerts()[0]
        assert stored["active"] is False
        assert stored["triggered_at"] is not None

    def test_idempotent_voi_id_khong_ton_tai(self, alerts):
        alerts.mark_triggered("khong-co-that")  # không được raise


class TestAiSignalChange:
    def test_lan_dau_luu_khong_tinh_la_doi(self, alerts):
        result = alerts.update_ai_signal("FPT", "BUY")
        assert result["changed"] is False
        assert result["previous"] is None
        assert result["current"] == "BUY"

    def test_doi_khuyen_nghi_thi_bao_changed(self, alerts):
        alerts.update_ai_signal("FPT", "BUY")
        result = alerts.update_ai_signal("FPT", "SELL")
        assert result["changed"] is True
        assert result["previous"] == "BUY"
        assert result["current"] == "SELL"

    def test_khuyen_nghi_giong_het_thi_khong_doi(self, alerts):
        alerts.update_ai_signal("FPT", "BUY")
        assert alerts.update_ai_signal("FPT", "buy")["changed"] is False

    def test_input_rong_khong_ghi_gi(self, alerts):
        assert alerts.update_ai_signal("", "BUY")["changed"] is False
        assert alerts.update_ai_signal("FPT", "")["changed"] is False


class TestCheckAlerts:
    def test_khong_co_rule_thi_tra_rong(self, alerts):
        assert alerts.check_alerts() == []

    def test_rule_da_kich_hoat_khong_duoc_check_lai(self, alerts, monkeypatch):
        rule = alerts.create_alert("FPT", "price_above", 1000)
        alerts.mark_triggered(rule["id"])

        # Nếu engine vẫn duyệt rule đã tắt, hàm fetch dưới đây sẽ bị gọi.
        called = []
        monkeypatch.setattr(
            alerts, "_fetch_symbol_snapshot", lambda symbol: called.append(symbol) or {}
        )
        assert alerts.check_alerts() == []
        assert called == []

    def test_gia_vuot_nguong_thi_kich_hoat(self, alerts, monkeypatch):
        alerts.create_alert("FPT", "price_above", 70000)
        monkeypatch.setattr(
            alerts,
            "_fetch_symbol_snapshot",
            lambda symbol: {"symbol": symbol, "price": 73600.0, "rsi": 60.0},
        )

        triggered = alerts.check_alerts()
        assert len(triggered) == 1
        assert triggered[0]["symbol"] == "FPT"
        # One-shot: rule phải tắt sau khi bắn, tránh spam mỗi lần poll.
        assert alerts.list_alerts()[0]["active"] is False

    def test_gia_chua_toi_nguong_thi_im(self, alerts, monkeypatch):
        alerts.create_alert("FPT", "price_above", 90000)
        monkeypatch.setattr(
            alerts,
            "_fetch_symbol_snapshot",
            lambda symbol: {"symbol": symbol, "price": 73600.0, "rsi": 60.0},
        )
        assert alerts.check_alerts() == []
        assert alerts.list_alerts()[0]["active"] is True


class TestAiSignalChangeAlert:
    """
    Rule "AI đổi tín hiệu" phải bắn được qua HAI request khác nhau: /analyze phát
    hiện đổi chiều, /alerts/check chạy sau đó mới đánh giá. Trạng thái vì thế phải
    nằm ở DB, không phải biến in-process.
    """

    def test_chua_co_tin_hieu_nao_thi_khong_bắn(self, alerts):
        alerts.create_alert("FPT", "ai_signal_change", 0)
        assert alerts.check_alerts() == []

    def test_tin_hieu_dau_tien_khong_tinh_la_doi(self, alerts):
        alerts.create_alert("FPT", "ai_signal_change", 0)
        alerts.update_ai_signal("FPT", "BUY")
        assert alerts.check_alerts() == []

    def test_doi_tin_hieu_thi_bắn_o_lan_check_ke_tiep(self, alerts):
        alerts.create_alert("FPT", "ai_signal_change", 0)
        alerts.update_ai_signal("FPT", "BUY")
        alerts.update_ai_signal("FPT", "SELL")

        triggered = alerts.check_alerts()
        assert [t["symbol"] for t in triggered] == ["FPT"]

    def test_pending_duoc_xoa_sau_khi_xu_ly(self, alerts):
        alerts.create_alert("FPT", "ai_signal_change", 0)
        alerts.update_ai_signal("FPT", "BUY")
        alerts.update_ai_signal("FPT", "SELL")
        alerts.check_alerts()

        # Rule mới cho cùng mã không được ăn theo lần đổi tín hiệu đã xử lý.
        alerts.create_alert("FPT", "ai_signal_change", 0)
        assert alerts.check_alerts() == []

    def test_ma_khac_khong_bi_bắn_lay(self, alerts):
        alerts.create_alert("HPG", "ai_signal_change", 0)
        alerts.update_ai_signal("FPT", "BUY")
        alerts.update_ai_signal("FPT", "SELL")
        assert alerts.check_alerts() == []


class TestNewsAlert:
    """
    Rule "có tin mới" — thứ người mới cần nhất mà lại khó tự cấu hình nhất.

    Điểm dễ sai: mốc so sánh. Nếu so với "lần check trước" thì mọi tin cũ đều bắn
    ngay lần check đầu tiên; phải so với lúc NGƯỜI DÙNG đặt cảnh báo.
    """

    def _stub_news(self, alerts, monkeypatch, published_at):
        items = [{"title": "FPT trung goi thau", "published_at": published_at, "url": "http://x"}]
        monkeypatch.setattr(alerts, "HAS_NEWS", True)
        monkeypatch.setattr(alerts, "get_recent_news", lambda symbol, limit=5: items)
        # Cache 10s dùng chung giữa các test trong cùng process.
        alerts._data_cache = type(alerts._data_cache)()

    def test_tin_cu_hon_luc_dat_thi_khong_ban(self, alerts, monkeypatch):
        alerts.create_alert("FPT", "news_new", 0)
        self._stub_news(alerts, monkeypatch, "2020-01-01T09:00:00")
        assert alerts.check_alerts() == []

    def test_tin_moi_hon_luc_dat_thi_ban(self, alerts, monkeypatch):
        alerts.create_alert("FPT", "news_new", 0)
        self._stub_news(alerts, monkeypatch, "2099-01-01T09:00:00")
        triggered = alerts.check_alerts()
        assert [t["symbol"] for t in triggered] == ["FPT"]

    def test_tieu_de_tin_di_kem_ket_qua(self, alerts, monkeypatch):
        # Báo "có tin" mà không nói tin gì thì người dùng vẫn phải tự đi mò.
        alerts.create_alert("FPT", "news_new", 0)
        self._stub_news(alerts, monkeypatch, "2099-01-01T09:00:00")
        triggered = alerts.check_alerts()
        assert triggered[0]["context"]["news"]["title"] == "FPT trung goi thau"

    def test_khong_lay_duoc_tin_thi_khong_ban(self, alerts, monkeypatch):
        alerts.create_alert("FPT", "news_new", 0)
        monkeypatch.setattr(alerts, "HAS_NEWS", True)
        monkeypatch.setattr(
            alerts, "get_recent_news", lambda symbol, limit=5: (_ for _ in ()).throw(RuntimeError("net"))
        )
        alerts._data_cache = type(alerts._data_cache)()
        assert alerts.check_alerts() == []

    def test_tin_thieu_ngay_thi_bo_qua(self, alerts, monkeypatch):
        alerts.create_alert("FPT", "news_new", 0)
        monkeypatch.setattr(alerts, "HAS_NEWS", True)
        monkeypatch.setattr(
            alerts, "get_recent_news", lambda symbol, limit=5: [{"title": "x", "published_at": None}]
        )
        alerts._data_cache = type(alerts._data_cache)()
        assert alerts.check_alerts() == []

    def test_ma_khac_khong_bi_ban_lay(self, alerts, monkeypatch):
        alerts.create_alert("HPG", "news_new", 0)
        monkeypatch.setattr(alerts, "HAS_NEWS", True)
        monkeypatch.setattr(alerts, "get_recent_news", lambda symbol, limit=5: [])
        alerts._data_cache = type(alerts._data_cache)()
        assert alerts.check_alerts() == []

    def test_ban_mot_lan_roi_thoi(self, alerts, monkeypatch):
        # One-shot: cùng một tin không được bắn lại ở lượt check kế tiếp, nếu không
        # người dùng sẽ bị nhắc lại cùng một tin mỗi phút.
        alerts.create_alert("FPT", "news_new", 0)
        self._stub_news(alerts, monkeypatch, "2099-01-01T09:00:00")
        assert len(alerts.check_alerts()) == 1
        assert alerts.check_alerts() == []


class TestParsePublishedAt:
    def test_iso_khong_timezone_hieu_la_gio_viet_nam(self, alerts):
        # Hiểu nhầm sang UTC sẽ đẩy mọi tin lùi 7 tiếng.
        from datetime import datetime, timedelta, timezone

        expected = datetime(2026, 8, 26, 17, 10, 5, tzinfo=timezone(timedelta(hours=7)))
        assert alerts._parse_published_at("2026-08-26T17:10:05") == int(expected.timestamp())

    def test_gia_tri_rac_tra_none(self, alerts):
        assert alerts._parse_published_at("hom qua") is None
        assert alerts._parse_published_at(None) is None
        assert alerts._parse_published_at("") is None
