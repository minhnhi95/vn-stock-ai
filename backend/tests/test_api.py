"""
Smoke test tầng HTTP: route nào tồn tại, validate đầu vào ra sao.

Chỉ gọi các route KHÔNG chạm mạng ngoài. Với route có gọi vnstock, chỉ test
nhánh validate (trả 400 trước khi kịp gọi mạng).
"""
from __future__ import annotations

import importlib
import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    """
    TestClient trên app thật, nhưng trỏ storage sang SQLite tạm.

    Env phải set TRƯỚC khi import main (main import storage_service ở top-level,
    mà storage_service đọc STOCK_DB_PATH lúc import).
    """
    with tempfile.TemporaryDirectory() as tmp:
        old_db_path = os.environ.get("STOCK_DB_PATH")
        old_db_url = os.environ.get("DATABASE_URL")
        os.environ["STOCK_DB_PATH"] = os.path.join(tmp, "api_test.db")
        os.environ.pop("DATABASE_URL", None)

        import storage_service

        importlib.reload(storage_service)
        import main

        importlib.reload(main)

        try:
            with TestClient(main.app) as test_client:
                yield test_client
        finally:
            if old_db_path is None:
                os.environ.pop("STOCK_DB_PATH", None)
            else:
                os.environ["STOCK_DB_PATH"] = old_db_path
            if old_db_url is not None:
                os.environ["DATABASE_URL"] = old_db_url
            importlib.reload(storage_service)


class TestHealth:
    def test_health_tra_ve_trang_thai_tung_service(self, client):
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        # Mọi service phase 2 phải import được; False nghĩa là route đó biến mất im lặng.
        assert all(body["services"].values()), f"service lỗi import: {body['services']}"

    def test_market_status_khong_can_mang(self, client):
        body = client.get("/api/market/status").json()
        assert body["status"] in {"OPEN", "LUNCH", "CLOSED"}
        assert isinstance(body["is_open"], bool)


class TestSearch:
    """
    Search chạy trên index danh sách niêm yết. Test bơm index giả để khỏi gọi
    vnstock và để thứ tự kết quả cố định.
    """

    @pytest.fixture(autouse=True)
    def stub_index(self, monkeypatch):
        import main
        import search_service

        def _entry(symbol, name, sector, alias=""):
            return {
                "symbol": symbol,
                "name": name,
                "sector": sector,
                "_name": search_service._fold(f"{name} {alias}"),
                "_sector": search_service._fold(sector),
            }

        entries = [
            _entry("FPT", "Công ty Cổ phần FPT", "Công nghệ Thông tin", "FPT Corp"),
            _entry("FRT", "Công ty Cổ phần Bán lẻ Kỹ thuật số FPT", "Bán lẻ", "FPT Retail"),
            _entry("HPG", "Công ty Cổ phần Tập đoàn Hòa Phát", "Tài nguyên Cơ bản", "Hoà Phát"),
            _entry("VNM", "Công ty Cổ phần Sữa Việt Nam", "Thực phẩm và đồ uống", "Vinamilk"),
        ]
        monkeypatch.setattr(search_service, "get_index", lambda: entries)
        monkeypatch.setattr(main, "get_search_index", lambda: entries)
        monkeypatch.setattr(search_service, "_liquidity_rank", lambda symbol: 0)
        return entries

    def test_query_rong_tra_danh_sach_pho_bien(self, client):
        results = client.get("/api/stocks/search").json()
        assert len(results) > 0
        assert all({"symbol", "name"} <= set(r) for r in results)

    def test_tim_theo_ma_uu_tien_khop_chinh_xac(self, client):
        results = client.get("/api/stocks/search", params={"query": "fpt"}).json()
        # Cả FPT lẫn FPT Retail đều khớp; mã trùng khít phải đứng đầu.
        assert results[0]["symbol"] == "FPT"
        assert "FRT" in [r["symbol"] for r in results]

    def test_tim_theo_ten_khong_dau(self, client):
        results = client.get("/api/stocks/search", params={"query": "hoa phat"}).json()
        assert [r["symbol"] for r in results] == ["HPG"]

    def test_tim_theo_ten_thuong_hieu(self, client):
        results = client.get("/api/stocks/search", params={"query": "vinamilk"}).json()
        assert [r["symbol"] for r in results] == ["VNM"]

    def test_ma_khong_co_that_khong_duoc_goi_y(self, client):
        # Có index thật thì không được bịa mã 3 chữ cái như trước.
        assert client.get("/api/stocks/search", params={"query": "XYZ"}).json() == []

    def test_chuoi_khong_phai_ma_thi_khong_goi_y(self, client):
        assert client.get("/api/stocks/search", params={"query": "ZZZZ"}).json() == []

    def test_ton_trong_limit(self, client):
        results = client.get("/api/stocks/search", params={"query": "cong ty", "limit": 2}).json()
        assert len(results) <= 2


class TestValidation:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/stocks/realtime",
            "/api/stocks/fundamentals",
            "/api/news",
            "/api/stocks/historical",
            "/api/foreign",
            "/api/insider",
            "/api/multitimeframe",
        ],
    )
    def test_ma_khong_hop_le_tra_400(self, client, path):
        response = client.get(path, params={"symbol": "AAPL"})
        assert response.status_code == 400
        assert "Việt Nam" in response.json()["detail"] or "không hợp lệ" in response.json()["detail"].lower()

    def test_thieu_symbol_tra_422(self, client):
        assert client.get("/api/stocks/realtime").status_code == 422



class TestVn30:
    def test_tra_ve_dung_30_ma(self, client):
        symbols = client.get("/api/vn30").json()["symbols"]
        assert len(symbols) == 30
        assert all(len(s) == 3 and s.isupper() for s in symbols)


class TestWatchPortfolioNews:
    """
    Một nút bật cảnh báo tin cho cả danh mục thật.

    Điểm dễ vỡ nhất không phải logic mà là ĐỊNH TUYẾN: '/api/alerts/watch-portfolio'
    khớp luôn vào '/api/alerts/{alert_id}' nếu route tĩnh khai báo sau, và FastAPI
    trả 405 chứ không phải 404 — rất dễ tưởng nhầm là lỗi phía client.
    """

    def test_route_ton_tai_va_nhan_post(self, client):
        response = client.post("/api/alerts/watch-portfolio")
        assert response.status_code != 405, "route bi '/api/alerts/{alert_id}' nuot mat"

    def test_danh_muc_rong_thi_bao_ro_rang(self, client):
        response = client.post("/api/alerts/watch-portfolio")
        assert response.status_code == 400
        assert "trống" in response.json()["detail"]

    def test_tao_rule_cho_moi_ma_dang_nam(self, client, monkeypatch):
        import main

        monkeypatch.setattr(
            main,
            "get_real_portfolio",
            lambda *a, **kw: {
                "positions": [
                    {"symbol": "FPT", "shares": 100},
                    {"symbol": "HPG", "shares": 500},
                    {"symbol": "VNM", "shares": 0},  # đã bán hết -> không theo dõi
                ]
            },
        )
        body = client.post("/api/alerts/watch-portfolio").json()
        assert body["created_count"] == 2
        assert sorted(c["symbol"] for c in body["created"]) == ["FPT", "HPG"]
        assert all(c["condition"] == "news_new" for c in body["created"])

    def test_bam_lai_khong_tao_rule_trung(self, client, monkeypatch):
        import main

        monkeypatch.setattr(
            main,
            "get_real_portfolio",
            lambda *a, **kw: {"positions": [{"symbol": "SSI", "shares": 10}]},
        )
        assert client.post("/api/alerts/watch-portfolio").json()["created_count"] == 1

        second = client.post("/api/alerts/watch-portfolio").json()
        assert second["created_count"] == 0
        assert second["skipped"] == ["SSI"]
