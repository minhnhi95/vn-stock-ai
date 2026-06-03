import React, { useEffect, useMemo, useState } from 'react';
import { Calendar, Coins, CalendarClock, RefreshCw } from 'lucide-react';

const fmtDate = (s) => {
  if (!s) return 'N/A';
  try {
    const d = new Date(s);
    if (Number.isNaN(d.getTime())) return s;
    const dd = String(d.getDate()).padStart(2, '0');
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    return `${dd}/${mm}`;
  } catch {
    return s;
  }
};

const daysUntil = (s) => {
  if (!s) return null;
  try {
    const d = new Date(s);
    if (Number.isNaN(d.getTime())) return null;
    const now = new Date();
    const ms = d.setHours(0, 0, 0, 0) - now.setHours(0, 0, 0, 0);
    return Math.round(ms / (1000 * 60 * 60 * 24));
  } catch {
    return null;
  }
};

const dayBadgeTone = (n) => {
  if (n === null || n === undefined) return '';
  if (n <= 3) return 'urgent';
  if (n <= 7) return 'soon';
  return 'normal';
};

const fmtRate = (rate, type) => {
  if (rate === null || rate === undefined || rate === '') return 'N/A';
  const num = Number(rate);
  if (Number.isNaN(num)) return String(rate);
  // tiền: nghìn đồng/cổ phiếu, cổ phiếu: tỷ lệ %
  if (type === 'stock' || type === 'co_phieu') {
    return `${num.toFixed(2)}%`;
  }
  return `${num.toLocaleString('vi-VN')} đ`;
};

const typeLabel = (t) => {
  if (!t) return '';
  const k = String(t).toLowerCase();
  if (k.includes('stock') || k.includes('co_phieu') || k.includes('cổ phiếu')) return 'Cổ phiếu';
  if (k.includes('cash') || k.includes('tien') || k.includes('tiền')) return 'Tiền mặt';
  return t;
};

const eventLabel = (t) => {
  if (!t) return 'Sự kiện';
  const k = String(t).toLowerCase();
  if (k.includes('agm') || k.includes('dhdcd') || k.includes('đhđcđ')) return 'ĐHĐCĐ';
  if (k.includes('earning')) return 'KQKD';
  if (k.includes('dividend')) return 'Cổ tức';
  if (k.includes('split')) return 'Chia tách';
  return t;
};

export default function CalendarPanel({ apiBase, watchlistSymbols = [] }) {
  const [data, setData] = useState({ dividends: [], events: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const symbolsKey = useMemo(() => {
    const uniq = Array.from(new Set((watchlistSymbols || []).filter(Boolean).map((s) => s.toUpperCase())));
    uniq.sort();
    return uniq.join(',');
  }, [watchlistSymbols]);

  const symbolsSet = useMemo(() => new Set(symbolsKey ? symbolsKey.split(',') : []), [symbolsKey]);

  const fetchCalendar = async () => {
    if (!apiBase) return;
    setLoading(true);
    setError(null);
    try {
      const url = symbolsKey
        ? `${apiBase}/calendar/upcoming?symbols=${encodeURIComponent(symbolsKey)}`
        : `${apiBase}/calendar/upcoming`;
      const res = await fetch(url);
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`);
      setData({
        dividends: Array.isArray(json.dividends) ? json.dividends : [],
        events: Array.isArray(json.events) ? json.events : [],
      });
    } catch (err) {
      setError(err.message || 'Không tải được lịch sự kiện');
      setData({ dividends: [], events: [] });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCalendar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbolsKey, apiBase]);

  const filteredDividends = useMemo(() => {
    if (!symbolsSet.size) return data.dividends;
    return data.dividends.filter((d) => d?.symbol && symbolsSet.has(String(d.symbol).toUpperCase()));
  }, [data.dividends, symbolsSet]);

  const filteredEvents = useMemo(() => {
    if (!symbolsSet.size) return data.events;
    return data.events.filter((e) => e?.symbol && symbolsSet.has(String(e.symbol).toUpperCase()));
  }, [data.events, symbolsSet]);

  const sortByDate = (a, b) => {
    const da = new Date(a?.date || a?.ex_date || 0).getTime() || 0;
    const db = new Date(b?.date || b?.ex_date || 0).getTime() || 0;
    return da - db;
  };

  const dividends = [...filteredDividends].sort(sortByDate);
  const events = [...filteredEvents].sort(sortByDate);

  const hasAny = dividends.length > 0 || events.length > 0;

  return (
    <div className="glass-panel">
      <div className="panel-header">
        <div className="panel-title">
          <Calendar size={16} className="text-accent" />
          <span>Lịch sự kiện 30 ngày</span>
        </div>
        <button className="cal-refresh" onClick={fetchCalendar} disabled={loading} title="Tải lại">
          <RefreshCw size={12} className={loading ? 'spin' : ''} />
        </button>
      </div>
      <div className="panel-content cal-content">
        {error ? <div className="cal-error">{error}</div> : null}

        {!hasAny && !loading && !error ? (
          <div className="cal-empty">Không có sự kiện sắp tới</div>
        ) : null}

        {dividends.length > 0 ? (
          <div className="cal-section">
            <div className="cal-section-title">
              <Coins size={12} />
              <span>Sắp chia cổ tức</span>
              <span className="cal-count">{dividends.length}</span>
            </div>
            <div className="cal-list">
              {dividends.map((d, i) => {
                const date = d.date || d.ex_date;
                const dn = daysUntil(date);
                const tone = dayBadgeTone(dn);
                return (
                  <div key={`div-${i}`} className="cal-row">
                    <span className="cal-symbol">{d.symbol}</span>
                    <span className="cal-date">
                      {fmtDate(date)}
                      {dn !== null ? <span className={`cal-daybadge ${tone}`}>T-{dn}</span> : null}
                    </span>
                    <span className="cal-rate">{fmtRate(d.rate, d.type)}</span>
                    <span className="cal-type">{typeLabel(d.type)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}

        {events.length > 0 ? (
          <div className="cal-section">
            <div className="cal-section-title">
              <CalendarClock size={12} />
              <span>Sự kiện sắp tới</span>
              <span className="cal-count">{events.length}</span>
            </div>
            <div className="cal-list">
              {events.map((e, i) => {
                const date = e.date;
                const dn = daysUntil(date);
                const tone = dayBadgeTone(dn);
                return (
                  <div key={`evt-${i}`} className="cal-row event-row">
                    <span className="cal-symbol">{e.symbol}</span>
                    <span className="cal-date">
                      {fmtDate(date)}
                      {dn !== null ? <span className={`cal-daybadge ${tone}`}>T-{dn}</span> : null}
                    </span>
                    <span className="cal-event-tag">{eventLabel(e.event_type)}</span>
                    <span className="cal-desc" title={e.description}>{e.description || '-'}</span>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}
      </div>

      <style>{`
        .cal-content {
          display: flex;
          flex-direction: column;
          gap: 12px;
          max-height: 380px;
          overflow-y: auto;
        }
        .cal-empty {
          text-align: center;
          font-size: 12px;
          color: var(--text-muted);
          padding: 24px 10px;
        }
        .cal-error {
          background: rgba(244, 63, 94, 0.1);
          border: 1px solid rgba(244, 63, 94, 0.3);
          color: #fda4af;
          padding: 6px 10px;
          border-radius: 6px;
          font-size: 10px;
        }
        .cal-refresh {
          background: transparent;
          border: 1px solid var(--border-color);
          color: var(--text-muted);
          width: 22px;
          height: 22px;
          border-radius: 4px;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
        }
        .cal-refresh:hover { color: var(--color-accent); border-color: var(--color-accent); }
        .cal-refresh:disabled { opacity: 0.5; cursor: not-allowed; }
        .cal-refresh .spin { animation: cal-spin 1s linear infinite; }
        @keyframes cal-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

        .cal-section {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .cal-section-title {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: 0.6px;
          color: var(--text-secondary);
          padding-bottom: 4px;
          border-bottom: 1px solid var(--border-color);
        }
        .cal-section-title svg { color: var(--color-accent); }
        .cal-count {
          margin-left: auto;
          background: rgba(6, 182, 212, 0.1);
          color: var(--color-accent);
          padding: 1px 6px;
          border-radius: 3px;
          font-weight: 600;
        }
        .cal-list {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .cal-row {
          display: grid;
          grid-template-columns: 56px 1fr 90px 80px;
          align-items: center;
          gap: 8px;
          padding: 7px 10px;
          background: rgba(0, 0, 0, 0.25);
          border: 1px solid var(--border-color);
          border-radius: 6px;
          font-size: 11px;
          transition: all 0.2s;
        }
        .cal-row:hover {
          background: rgba(6, 182, 212, 0.06);
          border-color: rgba(6, 182, 212, 0.3);
        }
        .cal-row.event-row {
          grid-template-columns: 56px 1fr 70px 1.4fr;
        }
        .cal-symbol {
          font-family: var(--font-display);
          font-weight: 700;
          color: var(--color-accent);
          font-size: 12px;
        }
        .cal-date {
          font-family: var(--font-display);
          color: var(--text-secondary);
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .cal-daybadge {
          font-size: 9px;
          padding: 1px 5px;
          border-radius: 3px;
          font-weight: 600;
          font-family: var(--font-display);
        }
        .cal-daybadge.urgent {
          background: rgba(244, 63, 94, 0.15);
          color: var(--color-sell);
        }
        .cal-daybadge.soon {
          background: rgba(234, 179, 8, 0.12);
          color: #facc15;
        }
        .cal-daybadge.normal {
          background: rgba(148, 163, 184, 0.12);
          color: var(--text-muted);
        }
        .cal-rate {
          font-family: var(--font-display);
          font-weight: 700;
          color: var(--color-buy);
          text-align: right;
        }
        .cal-type {
          font-size: 10px;
          color: var(--text-muted);
          text-align: right;
        }
        .cal-event-tag {
          font-size: 10px;
          font-weight: 600;
          background: rgba(6, 182, 212, 0.1);
          color: var(--color-accent);
          padding: 2px 6px;
          border-radius: 3px;
          text-align: center;
        }
        .cal-desc {
          color: var(--text-secondary);
          font-size: 11px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
      `}</style>
    </div>
  );
}
