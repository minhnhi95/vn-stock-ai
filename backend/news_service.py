"""
Lấy tin doanh nghiệp Việt Nam.

Chiến lược:
1. Thử vnstock.Company(symbol).news() (kênh chính - tin trực tiếp từ VCI/TCBS)
2. Fallback: tìm trong tin chung của thị trường (RSS CafeF) lọc theo mã

Trả về structure chuẩn để inject vào AI prompt + render UI.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from market_service import TTLCache

try:
    from vnstock import Company
    HAS_COMPANY = True
except ImportError:
    HAS_COMPANY = False

try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "models/text-embedding-004")
_embedding_cache: Dict[str, List[float]] = {}
_embedding_lock = threading.Lock()
# Lưu lại tất cả news đã ingest cho semantic search (in-memory).
_news_index: Dict[str, Dict[str, Any]] = {}  # key = url|title hash
_news_index_lock = threading.Lock()

NEWS_TTL_SECONDS = 1800.0  # 30 phút
RSS_CAFEF_MARKET = "https://cafef.vn/thi-truong-chung-khoan.rss"
USER_AGENT = "Mozilla/5.0 (compatible; VN-Stock-AI/1.0)"

_cache = TTLCache()


def _safe_str(v) -> str:
    try:
        return str(v) if v is not None else ""
    except Exception:
        return ""


def _google_search_url(title: str) -> str:
    """Fallback URL khi nguồn gốc không có link (vnstock free tier)."""
    from urllib.parse import quote_plus
    return f"https://www.google.com/search?q={quote_plus(title)}"


def _normalize_record(symbol: str, source: str, title: str, summary: str, url: str, published: str, image_url: str = "") -> Dict[str, Any]:
    clean_title = (title or "").strip()
    return {
        "symbol": symbol,
        "source": source,
        "title": clean_title,
        "summary": (summary or "").strip()[:600],
        "url": url or (_google_search_url(clean_title) if clean_title else ""),
        "has_real_url": bool(url),
        "image_url": (image_url or "").strip(),
        "published_at": published,
    }


def _fetch_company_news(symbol: str) -> List[Dict[str, Any]]:
    if not HAS_COMPANY:
        return []
    last_err = None
    for src in ("VCI", "TCBS"):
        try:
            c = Company(symbol=symbol, source=src)
            if not hasattr(c, "news"):
                continue
            df = c.news()
            if df is None or df.empty:
                continue

            cols = {c.lower(): c for c in df.columns}

            def col(*names):
                for n in names:
                    if n in cols:
                        return cols[n]
                return None

            title_col = col("news_title", "title", "tieu_de")
            url_col = col("news_source_link", "url", "link", "source_link")
            time_col = col("public_date", "published_date", "date", "publish_date", "ngay_dang")
            summary_col = col("news_short_content", "short_content", "summary", "noi_dung", "content")
            image_col = col("news_image_url", "image_url", "thumbnail")

            records = []
            for _, row in df.head(10).iterrows():
                title = _safe_str(row.get(title_col)) if title_col else ""
                if not title:
                    continue
                records.append(_normalize_record(
                    symbol=symbol,
                    source=f"vnstock/{src}",
                    title=title,
                    summary=_safe_str(row.get(summary_col)) if summary_col else "",
                    url=_safe_str(row.get(url_col)) if url_col else "",
                    published=_safe_str(row.get(time_col)) if time_col else "",
                    image_url=_safe_str(row.get(image_col)) if image_col else "",
                ))
            if records:
                return records
        except Exception as e:
            last_err = str(e)
            continue
    if last_err:
        print(f"[news] Company.news failed for {symbol}: {last_err}")
    return []


def _fetch_cafef_rss_for_symbol(symbol: str) -> List[Dict[str, Any]]:
    """Lọc tin từ RSS chung của CafeF theo mã (xuất hiện trong title/description)."""
    try:
        req = Request(RSS_CAFEF_MARKET, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=6) as resp:
            xml_data = resp.read()
    except Exception as e:
        print(f"[news] CafeF RSS fetch failed: {e}")
        return []

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        print(f"[news] CafeF RSS parse failed: {e}")
        return []

    pattern = re.compile(rf"\b{re.escape(symbol)}\b", re.IGNORECASE)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        desc = (item.findtext("description") or "").strip()
        # Loại bỏ HTML thô từ description CafeF
        desc_clean = re.sub(r"<[^>]+>", " ", desc).strip()
        haystack = f"{title} {desc_clean}"
        if not pattern.search(haystack):
            continue
        items.append(_normalize_record(
            symbol=symbol,
            source="CafeF",
            title=title,
            summary=desc_clean,
            url=(item.findtext("link") or "").strip(),
            published=(item.findtext("pubDate") or "").strip(),
        ))
        if len(items) >= 10:
            break
    return items


def _index_news(records: List[Dict[str, Any]]):
    """Thêm news vào index in-memory cho semantic search."""
    with _news_index_lock:
        for r in records:
            key = hashlib.sha1((r.get("url") or r.get("title", "")).encode("utf-8")).hexdigest()
            if key not in _news_index:
                _news_index[key] = r


def get_recent_news(symbol: str, limit: int = 5) -> List[Dict[str, Any]]:
    symbol = symbol.strip().upper()
    cache_key = f"news:{symbol}"

    cached = _cache.get(cache_key)
    if cached is not None:
        return cached[:limit]

    records = _fetch_company_news(symbol)
    if not records:
        records = _fetch_cafef_rss_for_symbol(symbol)

    if records:
        _cache.set(cache_key, records, NEWS_TTL_SECONDS)
        _index_news(records)
    return records[:limit]


def _embed_text(text: str, api_key: Optional[str]) -> Optional[List[float]]:
    if not HAS_GENAI:
        return None
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        return None

    text_norm = (text or "").strip()[:1500]
    if not text_norm:
        return None
    cache_key = hashlib.sha1(text_norm.encode("utf-8")).hexdigest()
    with _embedding_lock:
        if cache_key in _embedding_cache:
            return _embedding_cache[cache_key]

    try:
        genai.configure(api_key=key)
        result = genai.embed_content(
            model=EMBED_MODEL,
            content=text_norm,
            task_type="retrieval_document",
        )
        vec = result.get("embedding") if isinstance(result, dict) else getattr(result, "embedding", None)
        if vec is None:
            return None
        with _embedding_lock:
            _embedding_cache[cache_key] = list(vec)
        return list(vec)
    except Exception as e:
        print(f"[embed] failed: {e}")
        return None


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return -1.0
    return dot / (na * nb)


def search_news_semantic(
    query: str,
    top_k: int = 5,
    api_key: Optional[str] = None,
    symbol_filter: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Tìm tin theo ngữ nghĩa qua Gemini embeddings.
    Chỉ tìm trong các tin đã được ingest (gọi /api/news/{symbol} hoặc /api/ai/analyze).
    Trả về top-k tin có cosine similarity cao nhất.
    """
    if not HAS_GENAI:
        return {"ok": False, "error": "google-generativeai chưa được cài.", "results": []}

    q_vec = _embed_text(query, api_key)
    if q_vec is None:
        return {
            "ok": False,
            "error": "Không tạo được embedding cho query (thiếu API key hoặc lỗi mạng).",
            "results": [],
        }

    with _news_index_lock:
        candidates = list(_news_index.values())

    if symbol_filter:
        filter_upper = {s.upper() for s in symbol_filter}
        candidates = [c for c in candidates if (c.get("symbol", "").upper() in filter_upper)]

    if not candidates:
        return {
            "ok": True,
            "results": [],
            "note": "Index trống. Mở các mã ở UI hoặc chạy /api/news?symbol=XXX trước để ingest tin.",
        }

    scored = []
    for c in candidates:
        # Embed lười: chỉ gọi Gemini cho tin chưa có cache embedding,
        # rồi lưu vector vào chính news record trong index để tái sử dụng lần sau.
        if "_embedding" in c and c["_embedding"]:
            v = c["_embedding"]
        else:
            text_for_embed = f"{c.get('title', '')}. {c.get('summary', '')}"
            v = _embed_text(text_for_embed, api_key)
            if v is None:
                continue
            # Mutate trong index để các search sau hit cache
            with _news_index_lock:
                key = hashlib.sha1((c.get("url") or c.get("title", "")).encode("utf-8")).hexdigest()
                if key in _news_index:
                    _news_index[key]["_embedding"] = v
            c["_embedding"] = v
        score = _cosine(q_vec, v)
        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    def _strip_internal(item):
        return {k: v for k, v in item.items() if not k.startswith("_")}

    return {
        "ok": True,
        "query": query,
        "indexed_count": len(candidates),
        "results": [{"score": round(s, 4), **_strip_internal(item)} for s, item in top],
    }


def format_news_for_prompt(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "Tin tức gần đây: Không có tin nổi bật trong 30 phút qua."
    lines = ["Tin tức gần đây (đã lọc cho mã, dùng làm context bối cảnh):"]
    for i, it in enumerate(items, 1):
        date = it.get("published_at", "")
        title = it.get("title", "")
        snippet = (it.get("summary") or "")[:200]
        lines.append(f"{i}. [{date}] {title}")
        if snippet:
            lines.append(f"   Tóm tắt: {snippet}")
    return "\n".join(lines)
