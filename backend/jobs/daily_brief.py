"""
Bản tin sáng: gom dữ liệu -> đo phản ứng giá -> nhờ AI viết lại bằng tiếng Việt.

Nguyên tắc thiết kế quan trọng nhất: **AI không được đưa ra số, cũng không được
đưa ra khuyến nghị mua/bán.**

- Mọi con số (giá, %, khối lượng, vĩ mô) do code Python tính và đưa vào prompt.
  AI chỉ diễn đạt lại. Như vậy khi bản tin sai, ta biết sai ở tầng dữ liệu hay
  tầng diễn đạt.
- Schema output cố ý KHÔNG có trường "điểm số" hay "nên mua/bán". Người đọc mục
  tiêu là nhà đầu tư mới; một chữ "NÊN MUA" với họ là mệnh lệnh, còn một đoạn
  giải thích thì dạy họ cách tự nghĩ.
- Mỗi mục BẮT BUỘC có "điều gì làm nhận định này sai" — ép AI nêu mặt ngược lại.

Chạy: python -m jobs.daily_brief  (từ thư mục backend)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vnstock_safe  # noqa: F401,E402 - side effect: UTF-8 console + patch vnstock
from market_service import VN_TZ, market_status  # noqa: E402
from jobs.antigravity_client import (  # noqa: E402
    MODEL_DEEP,
    AntigravityError,
    is_available,
    run_agent,
)
from jobs.macro_context import fetch_macro_snapshot, format_macro_for_prompt  # noqa: E402
from jobs.price_reaction import analyze_reaction, format_reaction_for_prompt  # noqa: E402

# Số mã tối đa đưa vào bản tin. Giữ nhỏ vì mỗi mã tốn 1 lần fetch giá + tin,
# mà vnstock chỉ cho 20 request/phút.
MAX_SYMBOLS = 5
MAX_NEWS_PER_SYMBOL = 3

# Schema ép AI trả đúng cấu trúc. Cố ý không có "score" hay "recommendation".
BRIEF_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "tong_quan": {
            "type": "string",
            "description": "2-3 câu tóm tắt bối cảnh thị trường hôm nay, tiếng Việt đời thường.",
        },
        "boi_canh_the_gioi": {
            "type": "string",
            "description": "1-2 câu về vĩ mô thế giới, CHỈ dùng số liệu đã cho.",
        },
        "diem_tin": {
            "type": "array",
            "description": "Mỗi mã một mục. Không xếp hạng, không chấm điểm.",
            "items": {
                "type": "object",
                "properties": {
                    "ma": {"type": "string"},
                    "su_kien": {
                        "type": "string",
                        "description": "Chuyện gì đã xảy ra, 1-2 câu, dựa trên tin đã cho.",
                    },
                    "da_phan_anh": {
                        "type": "string",
                        "description": "Thị trường đã biết chưa. PHẢI dùng đúng số liệu phản ứng giá đã cho.",
                    },
                    "neu_dung_thi_sao": {
                        "type": "string",
                        "description": "Nếu tin này đúng thì ảnh hưởng tới doanh thu/lợi nhuận thế nào.",
                    },
                    "dieu_gi_lam_no_sai": {
                        "type": "string",
                        "description": "Mặt ngược lại: điều gì khiến nhận định trên không thành. BẮT BUỘC có.",
                    },
                    "can_luu_y": {
                        "type": "string",
                        "description": "Một câu hỏi để người đọc tự cân nhắc. KHÔNG được là lời khuyên mua/bán.",
                    },
                },
                "required": [
                    "ma",
                    "su_kien",
                    "da_phan_anh",
                    "neu_dung_thi_sao",
                    "dieu_gi_lam_no_sai",
                    "can_luu_y",
                ],
            },
        },
        "nhac_nho_rui_ro": {
            "type": "string",
            "description": "1-2 câu nhắc về rủi ro chung, không nói về mã cụ thể.",
        },
    },
    "required": ["tong_quan", "boi_canh_the_gioi", "diem_tin", "nhac_nho_rui_ro"],
}

_PROMPT_HEADER = """Bạn viết bản tin chứng khoán buổi sáng cho một nhà đầu tư cá nhân MỚI VÀO NGHỀ
ở Việt Nam. Người này không biết đọc chỉ báo kỹ thuật và dễ mua theo tin.

QUY TẮC BẮT BUỘC:
1. TUYỆT ĐỐI KHÔNG đưa khuyến nghị mua/bán/nắm giữ, không chấm điểm, không gắn
   nhãn tích cực/tiêu cực cho cổ phiếu. Nhiệm vụ của bạn là GIẢI THÍCH, không
   phải kết luận thay người đọc.
2. CHỈ dùng những con số có trong dữ liệu bên dưới. Không được tự thêm số liệu
   nào khác, kể cả khi bạn nghĩ mình biết. Không biết thì viết "chưa có dữ liệu".
3. Mục "điều gì làm nó sai" phải nêu được lý do CỤ THỂ, không viết chung chung
   kiểu "thị trường luôn có rủi ro".
4. Viết tiếng Việt đời thường, câu ngắn. Tránh từ chuyên ngành; nếu buộc phải
   dùng thì giải thích ngay trong ngoặc.
5. Mục "cần lưu ý" phải là một CÂU HỎI để người đọc tự cân nhắc, không phải lời
   khuyên hành động.

DỮ LIỆU:
"""


def _pick_symbols(explicit: Optional[List[str]] = None) -> List[str]:
    """
    Mã đưa vào bản tin: ưu tiên danh mục thật của người dùng, bù bằng VN30.

    Danh mục thật quan trọng hơn "mã hot" — người dùng cần biết tin về thứ họ
    đang cầm, chứ không phải thứ đang được bàn tán.
    """
    if explicit:
        return [s.strip().upper() for s in explicit if s.strip()][:MAX_SYMBOLS]

    symbols: List[str] = []
    try:
        from real_portfolio_service import get_real_portfolio

        data = get_real_portfolio(include_prices=False)
        symbols = [p["symbol"] for p in data.get("positions", [])]
    except Exception as e:
        print(f"[brief] không đọc được danh mục thật: {str(e)[:120]}")

    if len(symbols) < MAX_SYMBOLS:
        from market_universe import VN30_SYMBOLS

        for symbol in VN30_SYMBOLS:
            if symbol not in symbols:
                symbols.append(symbol)
            if len(symbols) >= MAX_SYMBOLS:
                break

    return symbols[:MAX_SYMBOLS]


def collect_evidence(symbols: List[str]) -> Dict[str, Any]:
    """
    Gom toàn bộ dữ liệu thật trước khi gọi AI.

    Tách hẳn bước này khỏi bước gọi AI để có thể kiểm tra dữ liệu đầu vào mà
    không tốn một lần gọi model.
    """
    from news_service import get_recent_news
    from stock_service import fetch_stock_data

    macro = fetch_macro_snapshot()
    per_symbol: List[Dict[str, Any]] = []

    for symbol in symbols:
        entry: Dict[str, Any] = {"symbol": symbol, "news": [], "reaction": None}
        try:
            news = get_recent_news(symbol, limit=MAX_NEWS_PER_SYMBOL) or []
            entry["news"] = [
                {
                    "title": n.get("title", ""),
                    "published_at": n.get("published_at", ""),
                    "source": n.get("source", ""),
                }
                for n in news
            ]
        except Exception as e:
            entry["news_error"] = str(e)[:120]

        try:
            df, _ = fetch_stock_data(symbol, period="6mo", interval="1d")
            newest_date = entry["news"][0]["published_at"] if entry["news"] else None
            entry["reaction"] = analyze_reaction(df, news_date=newest_date)
        except Exception as e:
            entry["reaction_error"] = str(e)[:120]

        per_symbol.append(entry)

    return {"macro": macro, "symbols": per_symbol, "market": market_status()}


def build_prompt(evidence: Dict[str, Any]) -> str:
    """Ghép dữ liệu đã gom thành prompt. Không có chỗ nào để AI tự tra cứu thêm."""
    blocks = [_PROMPT_HEADER, format_macro_for_prompt(evidence["macro"]), ""]

    market = evidence.get("market") or {}
    blocks.append(f"Phiên giao dịch hiện tại: {market.get('status')} — {market.get('reason')}")
    blocks.append("")

    for entry in evidence["symbols"]:
        symbol = entry["symbol"]
        blocks.append(f"===== {symbol} =====")
        if entry["news"]:
            blocks.append("Tin gần đây:")
            for item in entry["news"]:
                date = str(item.get("published_at", ""))[:10]
                blocks.append(f"- [{date}] {item['title']} (nguồn: {item.get('source', 'N/A')})")
        else:
            blocks.append("Tin gần đây: không có tin nào được ghi nhận.")

        reaction = entry.get("reaction")
        if reaction:
            blocks.append(format_reaction_for_prompt(symbol, reaction))
        blocks.append("")

    blocks.append(
        "Viết bản tin theo đúng schema. Mỗi mã ở trên một mục trong 'diem_tin'. "
        "Mã nào không có tin thì vẫn viết mục, ghi rõ là không có tin mới và chỉ "
        "mô tả diễn biến giá."
    )
    return "\n".join(blocks)


def generate_brief(
    symbols: Optional[List[str]] = None,
    model: str = MODEL_DEEP,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Chạy trọn quy trình. `dry_run=True` chỉ gom dữ liệu, không gọi AI.
    """
    started = time.monotonic()
    picked = _pick_symbols(symbols)
    print(f"[brief] mã đưa vào bản tin: {', '.join(picked)}")

    evidence = collect_evidence(picked)
    prompt = build_prompt(evidence)
    print(f"[brief] prompt {len(prompt)} ký tự")

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "symbols": picked,
            "prompt": prompt,
            "evidence": evidence,
        }

    if not is_available():
        raise AntigravityError(
            "Không tìm thấy Antigravity CLI (agy). Bản tin cần nó để sinh nội dung."
        )

    result = run_agent(prompt, model=model, schema=BRIEF_SCHEMA, timeout=420)
    print(
        f"[brief] {result.model} xong trong {result.duration_seconds}s "
        f"({result.input_tokens} token vào / {result.output_tokens} ra)"
    )

    now = datetime.now(VN_TZ)
    return {
        "ok": True,
        "date": now.date().isoformat(),
        "generated_at": now.isoformat(),
        "model": result.model,
        "symbols": picked,
        "content": result.data,
        "macro": evidence["macro"]["items"],
        "reactions": {
            e["symbol"]: e.get("reaction") for e in evidence["symbols"] if e.get("reaction")
        },
        "duration_seconds": round(time.monotonic() - started, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sinh bản tin chứng khoán buổi sáng")
    parser.add_argument("--symbols", nargs="*", help="Mã cụ thể (mặc định: danh mục thật + VN30)")
    parser.add_argument("--model", default=MODEL_DEEP, help="Model Antigravity")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ gom dữ liệu, không gọi AI")
    parser.add_argument("--no-save", action="store_true", help="Không ghi vào DB")
    parser.add_argument("--print-prompt", action="store_true", help="In prompt rồi thoát")
    args = parser.parse_args()

    try:
        brief = generate_brief(symbols=args.symbols, model=args.model, dry_run=args.dry_run)
    except AntigravityError as e:
        print(f"[brief] LỖI: {e}")
        return 1

    if args.print_prompt or args.dry_run:
        print("\n" + "=" * 60)
        print(brief["prompt"])
        return 0

    if not args.no_save:
        import storage_service as storage

        storage.save_daily_brief(brief["date"], brief)
        print(f"[brief] đã lưu bản tin ngày {brief['date']}")

    content = brief.get("content") or {}
    print("\n" + "=" * 60)
    print(content.get("tong_quan", ""))
    print("\n" + content.get("boi_canh_the_gioi", ""))
    for item in content.get("diem_tin", []):
        print(f"\n--- {item.get('ma')} ---")
        print(f"  Sự kiện    : {item.get('su_kien')}")
        print(f"  Đã phản ánh: {item.get('da_phan_anh')}")
        print(f"  Nếu đúng   : {item.get('neu_dung_thi_sao')}")
        print(f"  Có thể sai : {item.get('dieu_gi_lam_no_sai')}")
        print(f"  Cần lưu ý  : {item.get('can_luu_y')}")
    print("\n" + content.get("nhac_nho_rui_ro", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
