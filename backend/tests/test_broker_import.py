"""
Parser sao kê công ty chứng khoán.

Đây là cửa vào của dữ liệu tài chính thật, nên phần dễ sai nhất phải được khoá
chặt: định dạng số kiểu Việt Nam ('1.000' là một nghìn, KHÔNG phải 1,0) và việc
nhận diện Mua/Bán.
"""
from __future__ import annotations

import pytest

from broker_import_service import (
    ImportError_,
    _parse_date,
    _parse_number,
    _parse_side,
    build_manual_record,
    parse_broker_csv,
)


class TestParseNumber:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            # Kiểu Việt Nam: dấu chấm ngăn nghìn. '68.500' là sáu tám nghìn rưỡi.
            ("68.500", 68500.0),
            ("1.000", 1000.0),
            ("1.234.567", 1234567.0),
            ("1.234.567,89", 1234567.89),
            # Kiểu Anh - Mỹ.
            ("1,234,567.89", 1234567.89),
            ("68,500", 68500.0),
            # Số trần.
            ("102750", 102750.0),
            ("73.5", 73.5),
            ("0", 0.0),
        ],
    )
    def test_dinh_dang_so(self, raw, expected):
        assert _parse_number(raw) == expected

    def test_so_am_trong_ngoac(self):
        assert _parse_number("(1.500)") == -1500.0

    def test_so_am_dau_tru(self):
        assert _parse_number("-2.000") == -2000.0

    def test_bo_ky_tu_tien_te(self):
        assert _parse_number("68.500 đ") == 68500.0
        assert _parse_number("1.000.000 VND") == 1000000.0

    @pytest.mark.parametrize("raw", ["", "  ", "-", "--", None, "N/A"])
    def test_gia_tri_rong(self, raw):
        assert _parse_number(raw) is None


class TestParseDate:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("05/03/2026", "2026-03-05"),
            ("05-03-2026", "2026-03-05"),
            ("2026-03-05", "2026-03-05"),
            ("05.03.2026", "2026-03-05"),
            # Sao kê hay kèm giờ khớp lệnh.
            ("05/03/2026 09:31:22", "2026-03-05"),
        ],
    )
    def test_cac_dinh_dang(self, raw, expected):
        assert _parse_date(raw) == expected

    @pytest.mark.parametrize("raw", ["", None, "khong phai ngay", "32/13/2026"])
    def test_khong_hop_le(self, raw):
        assert _parse_date(raw) is None


class TestParseSide:
    @pytest.mark.parametrize("raw", ["Mua", "MUA", "Buy", "Khớp mua", "B"])
    def test_mua(self, raw):
        assert _parse_side(raw) == "BUY"

    @pytest.mark.parametrize("raw", ["Bán", "BÁN", "Sell", "Khớp bán", "S"])
    def test_ban(self, raw):
        assert _parse_side(raw) == "SELL"

    def test_ban_duoc_uu_tien_khi_chuoi_chua_ca_hai(self):
        # Cột kiểu "Mua/Bán" với giá trị "Bán" — nhận nhầm thành BUY là ghi sai sổ.
        assert _parse_side("Lệnh bán khớp") == "SELL"

    @pytest.mark.parametrize("raw", ["", None, "chuyển khoản", "cổ tức"])
    def test_khong_xac_dinh(self, raw):
        assert _parse_side(raw) is None


SSI_CSV = """SAO KE GIAO DICH CHUNG KHOAN
So tai khoan: 0123456789

Ngày giao dịch;Mã CK;Loại GD;Khối lượng khớp;Giá khớp;Phí giao dịch;Thuế TNCN
05/03/2026;FPT;Mua;1.000;68.500;102.750;0
15/07/2026;FPT;Bán;800;79.000;94.800;63.200
"""

NO_FEE_CSV = """Ngày,Mã CK,Lệnh,Số lượng,Giá
2026-03-05,HPG,Mua,2000,24300
2026-08-28,HPG,Bán,2000,22100
"""


class TestParseBrokerCsv:
    def test_bo_qua_dong_tieu_de_van_ban(self):
        result = parse_broker_csv(SSI_CSV.encode("utf-8"), "ssi.csv")
        assert len(result["records"]) == 2
        assert result["skipped"] == []

    def test_doc_dung_gia_tri(self):
        record = parse_broker_csv(SSI_CSV.encode("utf-8"), "ssi.csv")["records"][0]
        assert record["date"] == "2026-03-05"
        assert record["symbol"] == "FPT"
        assert record["side"] == "BUY"
        assert record["quantity"] == 1000
        assert record["price"] == 68500.0
        assert record["fee"] == 102750.0

    def test_dung_phi_trong_file_khi_co(self):
        result = parse_broker_csv(SSI_CSV.encode("utf-8"), "ssi.csv")
        assert result["fee_from_file"] is True

    def test_uoc_tinh_phi_va_thue_khi_file_khong_co(self):
        result = parse_broker_csv(NO_FEE_CSV.encode("utf-8"), "vps.csv", fee_rate=0.0015)
        assert result["fee_from_file"] is False
        buy, sell = result["records"]
        assert buy["fee"] == pytest.approx(2000 * 24300 * 0.0015)
        assert buy["tax"] == 0  # thuế TNCN chỉ thu khi bán
        assert sell["tax"] == pytest.approx(2000 * 22100 * 0.001)

    def test_ho_tro_dau_phay_lam_phan_cach(self):
        assert len(parse_broker_csv(NO_FEE_CSV.encode("utf-8"), "x.csv")["records"]) == 2

    def test_sap_xep_theo_ngay(self):
        records = parse_broker_csv(SSI_CSV.encode("utf-8"), "ssi.csv")["records"]
        assert [r["date"] for r in records] == sorted(r["date"] for r in records)

    def test_ext_id_on_dinh_giua_hai_lan_doc(self):
        # Cơ sở của việc chống nhập trùng khi sao kê các tháng chồng lấn nhau.
        first = parse_broker_csv(SSI_CSV.encode("utf-8"), "a.csv")["records"]
        second = parse_broker_csv(SSI_CSV.encode("utf-8"), "b.csv")["records"]
        assert [r["ext_id"] for r in first] == [r["ext_id"] for r in second]

    def test_dong_hong_bi_bo_kem_ly_do(self):
        csv = (
            "Ngày,Mã CK,Lệnh,Số lượng,Giá\n"
            "2026-03-05,FPT,Mua,1000,68500\n"
            "2026-03-06,KHONGHOPLE,Mua,100,1000\n"
            "khong-phai-ngay,HPG,Mua,100,1000\n"
        )
        result = parse_broker_csv(csv.encode("utf-8"), "x.csv")
        assert len(result["records"]) == 1
        assert len(result["skipped"]) == 2
        assert all("line" in s and "reason" in s for s in result["skipped"])

    def test_thieu_cot_bat_buoc_bao_loi_ro(self):
        csv = "Cột lạ,Cột khác\n1,2\n"
        with pytest.raises(ImportError_) as exc:
            parse_broker_csv(csv.encode("utf-8"), "x.csv")
        # Thông báo phải liệt kê cột đọc được để người dùng tự đối chiếu.
        assert "Cột lạ" in str(exc.value)

    def test_file_rong(self):
        with pytest.raises(ImportError_):
            parse_broker_csv(b"", "x.csv")

    def test_file_xlsx_hong_thi_huong_dan_chuyen_csv(self):
        with pytest.raises(ImportError_, match="CSV"):
            parse_broker_csv(b"PK\x03\x04", "sao_ke.xlsx")

    def test_doc_duoc_utf8_bom(self):
        result = parse_broker_csv(SSI_CSV.encode("utf-8-sig"), "ssi.csv")
        assert len(result["records"]) == 2


class TestBuildManualRecord:
    def test_ban_ghi_hop_le(self):
        record = build_manual_record("2026-03-05", "fpt", "buy", 1000, 68500)
        assert record["symbol"] == "FPT"
        assert record["side"] == "BUY"
        assert record["fee"] > 0
        assert record["tax"] == 0

    def test_lenh_ban_co_thue(self):
        record = build_manual_record("05/03/2026", "FPT", "SELL", 1000, 79000)
        assert record["tax"] == pytest.approx(1000 * 79000 * 0.001)

    def test_ext_id_khop_voi_ban_ghi_tu_file(self):
        # Nhập tay rồi nhập lại file chứa cùng lệnh đó thì không được nhân đôi.
        manual = build_manual_record("05/03/2026", "FPT", "BUY", 1000, 68500, fee=102750, tax=0)
        from_file = parse_broker_csv(SSI_CSV.encode("utf-8"), "ssi.csv")["records"][0]
        assert manual["ext_id"] == from_file["ext_id"]

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"date": "khong-phai-ngay", "symbol": "FPT", "side": "BUY", "quantity": 1, "price": 1},
            {"date": "2026-03-05", "symbol": "FPTX", "side": "BUY", "quantity": 1, "price": 1},
            {"date": "2026-03-05", "symbol": "FPT", "side": "HOLD", "quantity": 1, "price": 1},
            {"date": "2026-03-05", "symbol": "FPT", "side": "BUY", "quantity": 0, "price": 1},
            {"date": "2026-03-05", "symbol": "FPT", "side": "BUY", "quantity": 1, "price": 0},
        ],
    )
    def test_input_sai_bi_tu_choi(self, kwargs):
        with pytest.raises(ImportError_):
            build_manual_record(**kwargs)


class TestFileExcel:
    """Sao kê của công ty chứng khoán phần lớn xuất .xlsx, đọc thẳng khỏi phải đổi sang CSV."""

    def _xlsx(self, rows):
        import io as _io

        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        for row in rows:
            ws.append(row)
        buf = _io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_doc_duoc_sao_ke_xlsx(self):
        from datetime import datetime

        content = self._xlsx(
            [
                ["SAO KÊ GIAO DỊCH CHỨNG KHOÁN"],  # dòng tiêu đề trước bảng thật
                ["Ngày giao dịch", "Mã CK", "Loại GD", "Khối lượng", "Giá khớp", "Phí"],
                [datetime(2026, 9, 10), "FPT", "Mua", 300, 72700, 32715],
                ["11/09/2026", "DHC", "Bán", 500, 35750, 26812],
            ]
        )
        result = parse_broker_csv(content, filename="saoke.xlsx")
        rows = result["records"]
        assert [r["symbol"] for r in rows] == ["FPT", "DHC"]
        assert rows[0]["date"] == "2026-09-10" and rows[0]["side"] == "BUY"
        assert rows[1]["side"] == "SELL" and rows[1]["quantity"] == 500
        # Bán thì phải có thuế 0,1% dù file không tách cột thuế.
        assert rows[1]["tax"] > 0

    def test_file_xls_doi_cu_bao_ro(self):
        with pytest.raises(ImportError_, match="xls"):
            parse_broker_csv(b"rac", filename="saoke.xls")
