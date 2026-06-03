import React, { useState } from 'react';
import { Newspaper, ExternalLink, Search } from 'lucide-react';

export default function News({ items, symbol, apiBase, apiKey }) {
  const [query, setQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [searchResults, setSearchResults] = useState(null);
  const [searchError, setSearchError] = useState(null);

  const doSearch = async (e) => {
    e?.preventDefault?.();
    if (!query.trim()) return;
    setIsSearching(true);
    setSearchError(null);
    try {
      const res = await fetch(`${apiBase}/news/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, top_k: 5, apiKey }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      if (!data.ok) throw new Error(data.error || 'Search failed');
      setSearchResults(data);
    } catch (err) {
      setSearchError(err.message);
      setSearchResults(null);
    } finally {
      setIsSearching(false);
    }
  };

  const clearSearch = () => {
    setQuery('');
    setSearchResults(null);
    setSearchError(null);
  };

  const displayItems = searchResults?.results || items;
  const isSearchMode = !!searchResults;

  return (
    <div className="glass-panel">
      <div className="panel-header">
        <div className="panel-title">
          <Newspaper size={16} className="text-accent" />
          <span>{isSearchMode ? `Kết quả tìm "${searchResults.query}"` : `Tin tức gần đây: ${symbol}`}</span>
        </div>
        {displayItems?.length ? <span className="news-count">{displayItems.length} tin</span> : null}
      </div>
      <div className="panel-content news-list">
        <form className="news-search-form" onSubmit={doSearch}>
          <Search size={12} className="news-search-icon" />
          <input
            type="text"
            placeholder="Tìm theo ngữ nghĩa: 'kết quả kinh doanh quý 3', 'tăng vốn'..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {isSearchMode ? (
            <button type="button" className="news-search-btn" onClick={clearSearch}>Quay lại</button>
          ) : (
            <button type="submit" className="news-search-btn" disabled={isSearching || !query.trim()}>
              {isSearching ? '...' : 'Tìm'}
            </button>
          )}
        </form>
        {searchError ? <div className="news-error">{searchError}</div> : null}
        {!displayItems || displayItems.length === 0 ? (
          <div className="news-empty">
            {isSearchMode ? 'Không tìm thấy tin nào khớp.' : 'Chưa có tin tức nổi bật cho mã này.'}
          </div>
        ) : (
          displayItems.map((n, i) => (
            <a
              key={i}
              className="news-item"
              href={n.url || '#'}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => { if (!n.url) e.preventDefault(); }}
            >
              <div className="news-row">
                {n.image_url ? (
                  <img className="news-thumb" src={n.image_url} alt="" loading="lazy" onError={(e) => { e.currentTarget.style.display = 'none'; }} />
                ) : null}
                <div className="news-body">
                  <div className="news-title-row">
                    <span className="news-title">{n.title}</span>
                    {n.url ? <ExternalLink size={12} className="news-external" /> : null}
                  </div>
                  {n.summary ? <p className="news-summary">{n.summary}</p> : null}
                  <div className="news-meta">
                    <span className="news-source">{n.source}</span>
                    {n.symbol && n.symbol !== symbol ? <span className="news-symbol-tag">{n.symbol}</span> : null}
                    {n.published_at ? <span className="news-date">· {n.published_at}</span> : null}
                    {n.score !== undefined ? <span className="news-score">· score {n.score}</span> : null}
                    {n.has_real_url === false ? <span className="news-fallback-tag">↗ Google</span> : null}
                  </div>
                </div>
              </div>
            </a>
          ))
        )}
      </div>

      <style>{`
        .news-count {
          font-size: 10px;
          color: var(--text-muted);
        }
        .news-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
          max-height: 320px;
          overflow-y: auto;
        }
        .news-empty {
          text-align: center;
          font-size: 12px;
          color: var(--text-muted);
          padding: 20px 10px;
        }
        .news-item {
          display: flex;
          flex-direction: column;
          gap: 4px;
          padding: 10px 12px;
          background: rgba(0, 0, 0, 0.25);
          border: 1px solid var(--border-color);
          border-radius: 8px;
          text-decoration: none;
          color: inherit;
          transition: all 0.2s;
        }
        .news-item:hover {
          background: rgba(6, 182, 212, 0.06);
          border-color: rgba(6, 182, 212, 0.3);
        }
        .news-title-row {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 8px;
        }
        .news-title {
          font-size: 12px;
          font-weight: 600;
          color: var(--text-primary);
          line-height: 1.35;
        }
        .news-external {
          flex-shrink: 0;
          color: var(--text-muted);
        }
        .news-summary {
          font-size: 11px;
          color: var(--text-secondary);
          line-height: 1.5;
          margin: 0;
        }
        .news-meta {
          display: flex;
          gap: 4px;
          font-size: 10px;
          color: var(--text-muted);
          flex-wrap: wrap;
          align-items: center;
        }
        .news-row {
          display: flex;
          gap: 10px;
          align-items: flex-start;
        }
        .news-thumb {
          flex-shrink: 0;
          width: 56px;
          height: 56px;
          object-fit: cover;
          border-radius: 6px;
          border: 1px solid var(--border-color);
        }
        .news-body {
          flex-grow: 1;
          min-width: 0;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .news-symbol-tag {
          background: rgba(6, 182, 212, 0.1);
          color: var(--color-accent);
          padding: 1px 5px;
          border-radius: 3px;
          font-weight: 600;
        }
        .news-fallback-tag {
          background: rgba(234, 179, 8, 0.12);
          color: #facc15;
          padding: 1px 5px;
          border-radius: 3px;
          font-weight: 600;
        }
        .news-score {
          color: var(--color-accent);
          font-family: var(--font-display);
        }
        .news-search-form {
          display: flex;
          gap: 6px;
          align-items: center;
          background: rgba(0, 0, 0, 0.3);
          border: 1px solid var(--border-color);
          border-radius: 6px;
          padding: 4px 8px;
        }
        .news-search-form:focus-within { border-color: var(--color-accent); }
        .news-search-icon { color: var(--text-muted); flex-shrink: 0; }
        .news-search-form input {
          flex-grow: 1;
          background: transparent;
          border: none;
          color: #fff;
          font-size: 11px;
          padding: 4px 0;
        }
        .news-search-form input:focus { outline: none; }
        .news-search-btn {
          background: rgba(6, 182, 212, 0.15);
          border: 1px solid rgba(6, 182, 212, 0.3);
          color: var(--color-accent);
          padding: 3px 10px;
          border-radius: 4px;
          font-size: 10px;
          font-weight: 600;
          cursor: pointer;
        }
        .news-search-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .news-error {
          background: rgba(244, 63, 94, 0.1);
          border: 1px solid rgba(244, 63, 94, 0.3);
          color: #fda4af;
          padding: 6px 10px;
          border-radius: 6px;
          font-size: 10px;
        }
      `}</style>
    </div>
  );
}
