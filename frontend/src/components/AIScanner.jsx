import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Radar, RefreshCw, TrendingUp, TrendingDown, Minus, ArrowUpDown } from 'lucide-react';

const UNIVERSES = [
  { id: 'VN30', label: 'VN30', size: 30, etaSec: 25 },
  { id: 'VN100', label: 'VN100', size: 100, etaSec: 80 },
];

const fmt = (v, prec = 2) => {
  if (v === null || v === undefined || Number.isNaN(v)) return 'N/A';
  return Number(v).toFixed(prec);
};

const fmtPrice = (v) => {
  if (v === null || v === undefined || Number.isNaN(v)) return 'N/A';
  return Math.round(Number(v)).toLocaleString();
};

const fmtTimestamp = (ts) => {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return ts;
    const pad = (n) => String(n).padStart(2, '0');
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())} ${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`;
  } catch {
    return ts;
  }
};

const trendInfo = (trend) => {
  if (!trend) return { Icon: Minus, cls: 'neutral', label: '—' };
  const t = String(trend).toLowerCase();
  if (t === 'up' || t === 'bullish' || t === 'tăng') return { Icon: TrendingUp, cls: 'good', label: 'Tăng' };
  if (t === 'down' || t === 'bearish' || t === 'giảm') return { Icon: TrendingDown, cls: 'bad', label: 'Giảm' };
  return { Icon: Minus, cls: 'neutral', label: 'Đi ngang' };
};

const scoreTone = (score) => {
  if (score === null || score === undefined || Number.isNaN(score)) return 'neutral';
  if (score >= 70) return 'good';
  if (score >= 45) return 'mid';
  return 'bad';
};

const COLUMNS = [
  { id: 'rank', label: '#', sortable: false, width: '36px', align: 'left' },
  { id: 'symbol', label: 'Mã', sortable: true, width: '60px', align: 'left' },
  { id: 'score', label: 'Score', sortable: true, width: '1.4fr', align: 'left' },
  { id: 'signal_age_days', label: 'Tín hiệu', sortable: true, width: '80px', align: 'right' },
  { id: 'close', label: 'Giá', sortable: true, width: '80px', align: 'right' },
  { id: 'rsi', label: 'RSI', sortable: true, width: '60px', align: 'right' },
  { id: 'macd_hist', label: 'MACD H', sortable: true, width: '70px', align: 'right' },
  { id: 'ema_trend', label: 'EMA', sortable: true, width: '70px', align: 'center' },
];

export default function AIScanner({ apiBase, apiKey, onSelectSymbol }) {
  const [universe, setUniverse] = useState('VN30');
  const [isScanning, setIsScanning] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [sortBy, setSortBy] = useState('score');
  const [sortDir, setSortDir] = useState('desc');
  const [elapsed, setElapsed] = useState(0);

  const timerRef = useRef(null);

  const currentUniverse = useMemo(
    () => UNIVERSES.find(u => u.id === universe) || UNIVERSES[0],
    [universe]
  );

  useEffect(() => {
    if (isScanning) {
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed(e => e + 1), 1000);
    } else if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [isScanning]);

  const runScan = async () => {
    setIsScanning(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/scanner/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ universe, api_key: apiKey }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }
      const payload = await res.json();
      setData(payload);
      setSortBy('score');
      setSortDir('desc');
    } catch (e) {
      setError(e.message || 'Lỗi khi chạy scanner');
    } finally {
      setIsScanning(false);
    }
  };

  const handleSort = (col) => {
    if (!col.sortable) return;
    if (sortBy === col.id) {
      setSortDir(d => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortBy(col.id);
      // Default direction by column type
      const ascByDefault = ['symbol', 'signal_age_days'].includes(col.id);
      setSortDir(ascByDefault ? 'asc' : 'desc');
    }
  };

  const sortedRows = useMemo(() => {
    const rows = data?.results || data?.opportunities || [];
    if (!rows.length) return [];
    const copy = [...rows];
    copy.sort((a, b) => {
      const va = a[sortBy];
      const vb = b[sortBy];
      if (sortBy === 'symbol' || sortBy === 'ema_trend') {
        const sa = (va || '').toString();
        const sb = (vb || '').toString();
        return sortDir === 'asc' ? sa.localeCompare(sb) : sb.localeCompare(sa);
      }
      const na = (va === null || va === undefined || Number.isNaN(va)) ? -Infinity : Number(va);
      const nb = (vb === null || vb === undefined || Number.isNaN(vb)) ? -Infinity : Number(vb);
      return sortDir === 'asc' ? na - nb : nb - na;
    });
    return copy;
  }, [data, sortBy, sortDir]);

  const gridTemplate = COLUMNS.map(c => c.width).join(' ');

  const scannedAt = data?.scanned_at || data?.timestamp || null;
  const universeCount = data?.universe_size || data?.total || sortedRows.length;

  return (
    <div className="glass-panel">
      <div className="panel-header scanner-header">
        <div className="panel-title">
          <Radar size={16} className="text-accent" />
          <span>AI Scanner</span>
        </div>
        <div className="scanner-controls">
          <select
            className="scanner-select"
            value={universe}
            onChange={(e) => setUniverse(e.target.value)}
            disabled={isScanning}
          >
            {UNIVERSES.map(u => (
              <option key={u.id} value={u.id}>{u.label} ({u.size} mã)</option>
            ))}
          </select>
          <button
            className="btn btn-primary scanner-rescan-btn"
            onClick={runScan}
            disabled={isScanning}
          >
            <RefreshCw size={12} className={isScanning ? 'spin' : ''} />
            {data ? 'Quét lại' : 'Quét'}
          </button>
        </div>
      </div>

      <div className="panel-content scanner-content">
        {error && <div className="scanner-error">{error}</div>}

        {isScanning ? (
          <div className="scanner-loading">
            <div className="scanner-loading-spinner">
              <RefreshCw size={28} className="spin" />
            </div>
            <div className="scanner-loading-text">
              Đang quét {currentUniverse.size} mã {currentUniverse.label}...
            </div>
            <div className="scanner-loading-eta">
              Ước tính ~{currentUniverse.etaSec}s · đã chạy {elapsed}s
            </div>
            <div className="scanner-loading-bar">
              <div
                className="scanner-loading-fill"
                style={{ width: `${Math.min(95, (elapsed / currentUniverse.etaSec) * 100)}%` }}
              />
            </div>
          </div>
        ) : !data ? (
          <div className="scanner-empty">
            <Radar size={28} className="scanner-empty-icon" />
            <div className="scanner-empty-title">Chưa quét lần nào</div>
            <div className="scanner-empty-hint">
              Chọn universe và nhấn "Quét" để tìm top cơ hội theo điểm AI.
            </div>
          </div>
        ) : sortedRows.length === 0 ? (
          <div className="scanner-empty">
            <div className="scanner-empty-title">Không có cơ hội nào</div>
            <div className="scanner-empty-hint">Thử quét lại sau hoặc đổi universe.</div>
          </div>
        ) : (
          <>
            <div className="scanner-meta">
              <span>{sortedRows.length} cơ hội · {universeCount} mã đã quét</span>
              {scannedAt && <span className="scanner-meta-time">Cập nhật: {fmtTimestamp(scannedAt)}</span>}
            </div>

            <div className="scanner-table">
              <div
                className="scanner-row scanner-head"
                style={{ gridTemplateColumns: gridTemplate }}
              >
                {COLUMNS.map(c => (
                  <span
                    key={c.id}
                    className={`scanner-th align-${c.align} ${c.sortable ? 'sortable' : ''} ${sortBy === c.id ? 'active' : ''}`}
                    onClick={() => handleSort(c)}
                  >
                    {c.label}
                    {c.sortable && (
                      <ArrowUpDown
                        size={9}
                        className={`scanner-sort-icon ${sortBy === c.id ? `dir-${sortDir}` : ''}`}
                      />
                    )}
                  </span>
                ))}
              </div>

              {sortedRows.map((r, i) => {
                const trend = trendInfo(r.ema_trend);
                const TrendIcon = trend.Icon;
                const score = r.score;
                const tone = scoreTone(score);
                const scorePct = Math.max(0, Math.min(100, Number(score) || 0));
                const age = r.signal_age_days;

                return (
                  <div
                    key={r.symbol || i}
                    className="scanner-row scanner-data-row"
                    style={{ gridTemplateColumns: gridTemplate }}
                    onClick={() => onSelectSymbol && r.symbol && onSelectSymbol(r.symbol)}
                  >
                    <span className="scanner-rank">#{i + 1}</span>
                    <span className="scanner-symbol">{r.symbol}</span>
                    <span className="scanner-score-cell">
                      <span className={`scanner-score-bar tone-${tone}`}>
                        <span
                          className="scanner-score-fill"
                          style={{ width: `${scorePct}%` }}
                        />
                      </span>
                      <span className={`scanner-score-num tone-${tone}`}>
                        {fmt(score, 0)}
                      </span>
                    </span>
                    <span className="align-right scanner-age">
                      {age === null || age === undefined
                        ? 'N/A'
                        : age === 0
                          ? 'Hôm nay'
                          : `${age} phiên trước`}
                    </span>
                    <span className="align-right scanner-price">{fmtPrice(r.close)}</span>
                    <span className={`align-right ${r.rsi > 70 ? 'bad' : r.rsi < 30 ? 'good' : ''}`}>
                      {fmt(r.rsi, 1)}
                    </span>
                    <span className={`align-right ${r.macd_hist >= 0 ? 'good' : 'bad'}`}>
                      {fmt(r.macd_hist, 3)}
                    </span>
                    <span className={`align-center scanner-trend tone-${trend.cls}`} title={trend.label}>
                      <TrendIcon size={14} />
                    </span>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      <style>{`
        .scanner-header {
          gap: 10px;
          flex-wrap: wrap;
        }
        .scanner-controls {
          display: flex;
          gap: 8px;
          align-items: center;
        }
        .scanner-select {
          background: rgba(0, 0, 0, 0.3);
          border: 1px solid var(--border-color);
          border-radius: 6px;
          padding: 5px 8px;
          color: #fff;
          font-size: 11px;
          font-family: var(--font-display);
          cursor: pointer;
        }
        .scanner-select:disabled { opacity: 0.5; cursor: not-allowed; }
        .scanner-rescan-btn {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          font-size: 11px;
          padding: 5px 10px;
        }
        .scanner-content {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .scanner-error {
          background: rgba(244, 63, 94, 0.12);
          border: 1px solid rgba(244, 63, 94, 0.4);
          color: #ffd9e0;
          padding: 8px 12px;
          border-radius: 6px;
          font-size: 11px;
        }

        /* Loading */
        .scanner-loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 8px;
          padding: 28px 12px;
        }
        .scanner-loading-spinner {
          color: var(--color-accent);
        }
        .scanner-loading-text {
          font-size: 13px;
          font-weight: 600;
          color: var(--text-primary);
        }
        .scanner-loading-eta {
          font-size: 11px;
          color: var(--text-muted);
          font-family: var(--font-display);
        }
        .scanner-loading-bar {
          width: 100%;
          max-width: 280px;
          height: 4px;
          background: rgba(255, 255, 255, 0.05);
          border-radius: 2px;
          overflow: hidden;
          margin-top: 6px;
        }
        .scanner-loading-fill {
          height: 100%;
          background: linear-gradient(90deg, var(--color-accent), #06b6d4);
          transition: width 0.6s ease-out;
        }

        /* Empty */
        .scanner-empty {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 6px;
          padding: 30px 12px;
          text-align: center;
        }
        .scanner-empty-icon { color: var(--text-muted); margin-bottom: 4px; }
        .scanner-empty-title {
          font-size: 13px;
          font-weight: 600;
          color: var(--text-secondary);
        }
        .scanner-empty-hint {
          font-size: 11px;
          color: var(--text-muted);
          max-width: 320px;
          line-height: 1.4;
        }

        /* Meta */
        .scanner-meta {
          display: flex;
          justify-content: space-between;
          align-items: center;
          font-size: 10px;
          color: var(--text-muted);
          text-transform: uppercase;
          letter-spacing: 0.3px;
        }
        .scanner-meta-time {
          font-family: var(--font-display);
          text-transform: none;
          letter-spacing: 0;
        }

        /* Table */
        .scanner-table {
          display: flex;
          flex-direction: column;
          gap: 2px;
          max-height: 420px;
          overflow-y: auto;
        }
        .scanner-row {
          display: grid;
          gap: 8px;
          padding: 7px 10px;
          font-size: 11px;
          font-family: var(--font-display);
          border-radius: 4px;
          align-items: center;
        }
        .scanner-head {
          color: var(--text-muted);
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: 0.3px;
          border-bottom: 1px solid var(--border-color);
          margin-bottom: 4px;
          padding-top: 4px;
          padding-bottom: 6px;
          position: sticky;
          top: 0;
          background: rgba(2, 6, 23, 0.85);
          backdrop-filter: blur(4px);
          z-index: 2;
        }
        .scanner-th {
          display: inline-flex;
          align-items: center;
          gap: 3px;
        }
        .scanner-th.sortable {
          cursor: pointer;
          user-select: none;
        }
        .scanner-th.sortable:hover { color: var(--text-secondary); }
        .scanner-th.active { color: var(--color-accent); }
        .scanner-sort-icon { opacity: 0.4; }
        .scanner-th.active .scanner-sort-icon { opacity: 1; }
        .scanner-sort-icon.dir-desc { transform: rotate(180deg); }

        .align-left { text-align: left; justify-content: flex-start; }
        .align-right { text-align: right; justify-content: flex-end; }
        .align-center { text-align: center; justify-content: center; }

        .scanner-data-row {
          background: rgba(0, 0, 0, 0.2);
          cursor: pointer;
          transition: all 0.12s ease-out;
          border: 1px solid transparent;
        }
        .scanner-data-row:hover {
          background: rgba(6, 182, 212, 0.06);
          border-color: rgba(6, 182, 212, 0.25);
          transform: translateX(2px);
        }
        .scanner-rank { color: var(--text-muted); font-size: 10px; }
        .scanner-symbol {
          font-weight: 700;
          color: #fff;
          font-size: 12px;
          letter-spacing: 0.3px;
        }
        .scanner-price { color: var(--text-primary); }
        .scanner-age { color: var(--text-secondary); font-size: 10px; }

        /* Score bar */
        .scanner-score-cell {
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .scanner-score-bar {
          flex-grow: 1;
          height: 6px;
          background: rgba(255, 255, 255, 0.05);
          border-radius: 3px;
          overflow: hidden;
          min-width: 50px;
        }
        .scanner-score-fill {
          display: block;
          height: 100%;
          border-radius: 3px;
          transition: width 0.4s ease-out;
        }
        .scanner-score-bar.tone-good .scanner-score-fill { background: var(--color-buy); }
        .scanner-score-bar.tone-mid .scanner-score-fill { background: var(--color-accent); }
        .scanner-score-bar.tone-bad .scanner-score-fill { background: var(--color-sell); }
        .scanner-score-bar.tone-neutral .scanner-score-fill { background: var(--text-muted); }
        .scanner-score-num {
          font-weight: 700;
          font-size: 12px;
          min-width: 26px;
          text-align: right;
        }
        .scanner-score-num.tone-good { color: var(--color-buy); }
        .scanner-score-num.tone-mid { color: var(--color-accent); }
        .scanner-score-num.tone-bad { color: var(--color-sell); }
        .scanner-score-num.tone-neutral { color: var(--text-secondary); }

        /* Trend */
        .scanner-trend.tone-good { color: var(--color-buy); }
        .scanner-trend.tone-bad { color: var(--color-sell); }
        .scanner-trend.tone-neutral { color: var(--text-muted); }

        /* Row-level good / bad shorthand */
        .scanner-data-row .good { color: var(--color-buy); }
        .scanner-data-row .bad { color: var(--color-sell); }

        /* Spin */
        .spin { animation: scanner-spin 1s linear infinite; }
        @keyframes scanner-spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
