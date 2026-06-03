import React, { useEffect, useMemo, useState } from 'react';
import { Users, TrendingUp, TrendingDown, ArrowRightLeft, AlertCircle } from 'lucide-react';

const fmtVN = (n) => {
  if (n === null || n === undefined || Number.isNaN(n)) return 'N/A';
  const abs = Math.abs(Number(n));
  if (abs >= 1e12) return `${(n / 1e12).toFixed(2)} nghìn tỷ`;
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)} tỷ`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(1)} triệu`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return Number(n).toLocaleString('vi-VN');
};

const fmtShares = (n) => {
  if (n === null || n === undefined || Number.isNaN(n)) return 'N/A';
  return Number(n).toLocaleString('vi-VN');
};

const fmtDate = (d) => {
  if (!d) return '—';
  try {
    const date = new Date(d);
    if (Number.isNaN(date.getTime())) return d;
    return date.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' });
  } catch {
    return d;
  }
};

const isBuyType = (t) => {
  if (!t) return false;
  const s = String(t).toLowerCase();
  return s.includes('mua') || s.includes('buy');
};

export default function InsiderPanel({ apiBase, symbol }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!symbol || !apiBase) return;
    let aborted = false;
    const ctrl = new AbortController();

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${apiBase}/insider?symbol=${encodeURIComponent(symbol)}&days=30`, {
          signal: ctrl.signal,
        });
        const json = await res.json();
        if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`);
        if (aborted) return;
        setData(json);
      } catch (err) {
        if (err.name === 'AbortError') return;
        if (!aborted) {
          setError(err.message || 'Không thể tải dữ liệu giao dịch nội bộ');
          setData(null);
        }
      } finally {
        if (!aborted) setLoading(false);
      }
    };

    load();
    return () => {
      aborted = true;
      ctrl.abort();
    };
  }, [apiBase, symbol]);

  const summary = data?.summary || {};
  const deals = data?.deals || [];

  const netTone = useMemo(() => {
    const net = Number(summary.net);
    if (!Number.isFinite(net) || net === 0) return 'neutral';
    return net > 0 ? 'buy' : 'sell';
  }, [summary.net]);

  return (
    <div className="glass-panel">
      <div className="panel-header">
        <div className="panel-title">
          <Users size={16} className="text-accent" />
          <span>Giao dịch nội bộ: {symbol}</span>
        </div>
        <span className="insider-period">30 ngày qua</span>
      </div>
      <div className="panel-content insider-body">
        {loading ? (
          <div className="insider-empty">Đang tải dữ liệu...</div>
        ) : error ? (
          <div className="insider-error">
            <AlertCircle size={12} />
            <span>{error}</span>
          </div>
        ) : (
          <>
            <div className="insider-summary">
              <div className="insider-summary-cell buy">
                <div className="insider-summary-head">
                  <TrendingUp size={12} />
                  <span>Tổng MUA</span>
                </div>
                <div className="insider-summary-value">{fmtVN(summary.buy_value)}</div>
              </div>
              <div className="insider-summary-cell sell">
                <div className="insider-summary-head">
                  <TrendingDown size={12} />
                  <span>Tổng BÁN</span>
                </div>
                <div className="insider-summary-value">{fmtVN(summary.sell_value)}</div>
              </div>
              <div className={`insider-summary-cell net ${netTone}`}>
                <div className="insider-summary-head">
                  <ArrowRightLeft size={12} />
                  <span>Net signal</span>
                </div>
                <div className="insider-summary-value">
                  {summary.net !== undefined && summary.net !== null
                    ? `${Number(summary.net) > 0 ? '+' : ''}${fmtVN(summary.net)}`
                    : 'N/A'}
                </div>
              </div>
            </div>

            {!deals.length ? (
              <div className="insider-empty">
                Không có giao dịch nội bộ nào được ghi nhận trong 30 ngày qua.
              </div>
            ) : (
              <div className="insider-table-wrap">
                <table className="insider-table">
                  <thead>
                    <tr>
                      <th>Ngày</th>
                      <th>Người giao dịch</th>
                      <th className="ta-center">Loại</th>
                      <th className="ta-right">Cổ phiếu</th>
                      <th className="ta-right">Giá trị</th>
                      <th>Lý do</th>
                    </tr>
                  </thead>
                  <tbody>
                    {deals.map((d, i) => {
                      const buy = isBuyType(d.type);
                      return (
                        <tr key={i}>
                          <td className="insider-date">{fmtDate(d.date)}</td>
                          <td>
                            <div className="insider-person">{d.person || d.name || '—'}</div>
                            {d.role ? <div className="insider-role">{d.role}</div> : null}
                          </td>
                          <td className="ta-center">
                            <span className={`insider-badge ${buy ? 'buy' : 'sell'}`}>
                              {buy ? 'MUA' : 'BÁN'}
                            </span>
                          </td>
                          <td className="ta-right insider-num">{fmtShares(d.shares)}</td>
                          <td className={`ta-right insider-num ${buy ? 'val-buy' : 'val-sell'}`}>
                            {fmtVN(d.value)}
                          </td>
                          <td className="insider-reason">{d.reason || '—'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>

      <style>{`
        .insider-period {
          font-size: 10px;
          color: var(--text-muted);
        }
        .insider-body {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .insider-empty {
          padding: 20px 10px;
          text-align: center;
          color: var(--text-muted);
          font-size: 12px;
        }
        .insider-error {
          display: flex;
          align-items: center;
          gap: 6px;
          background: rgba(244, 63, 94, 0.1);
          border: 1px solid rgba(244, 63, 94, 0.3);
          color: #fda4af;
          padding: 8px 10px;
          border-radius: 6px;
          font-size: 11px;
        }
        .insider-summary {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 8px;
        }
        .insider-summary-cell {
          background: rgba(0, 0, 0, 0.25);
          border: 1px solid var(--border-color);
          border-radius: 8px;
          padding: 8px 10px;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .insider-summary-cell.buy {
          border-color: rgba(34, 197, 94, 0.3);
          background: rgba(34, 197, 94, 0.06);
        }
        .insider-summary-cell.sell {
          border-color: rgba(244, 63, 94, 0.3);
          background: rgba(244, 63, 94, 0.06);
        }
        .insider-summary-cell.net.buy {
          border-color: rgba(34, 197, 94, 0.4);
          background: rgba(34, 197, 94, 0.1);
        }
        .insider-summary-cell.net.sell {
          border-color: rgba(244, 63, 94, 0.4);
          background: rgba(244, 63, 94, 0.1);
        }
        .insider-summary-cell.net.neutral {
          border-color: rgba(6, 182, 212, 0.3);
          background: rgba(6, 182, 212, 0.06);
        }
        .insider-summary-head {
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: 10px;
          color: var(--text-muted);
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .insider-summary-cell.buy .insider-summary-head { color: var(--color-buy); }
        .insider-summary-cell.sell .insider-summary-head { color: var(--color-sell); }
        .insider-summary-cell.net.buy .insider-summary-head { color: var(--color-buy); }
        .insider-summary-cell.net.sell .insider-summary-head { color: var(--color-sell); }
        .insider-summary-cell.net.neutral .insider-summary-head { color: var(--color-accent); }
        .insider-summary-value {
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 14px;
          color: var(--text-primary);
        }
        .insider-summary-cell.buy .insider-summary-value { color: var(--color-buy); }
        .insider-summary-cell.sell .insider-summary-value { color: var(--color-sell); }
        .insider-summary-cell.net.buy .insider-summary-value { color: var(--color-buy); }
        .insider-summary-cell.net.sell .insider-summary-value { color: var(--color-sell); }
        .insider-table-wrap {
          max-height: 280px;
          overflow-y: auto;
          border: 1px solid var(--border-color);
          border-radius: 8px;
          background: rgba(0, 0, 0, 0.25);
        }
        .insider-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 11px;
        }
        .insider-table thead th {
          position: sticky;
          top: 0;
          background: rgba(0, 0, 0, 0.85);
          color: var(--text-muted);
          font-weight: 600;
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          padding: 8px 10px;
          text-align: left;
          border-bottom: 1px solid var(--border-color);
        }
        .insider-table tbody td {
          padding: 8px 10px;
          border-bottom: 1px solid var(--border-color);
          color: var(--text-secondary);
          vertical-align: top;
        }
        .insider-table tbody tr:last-child td {
          border-bottom: none;
        }
        .insider-table tbody tr:hover td {
          background: rgba(6, 182, 212, 0.04);
        }
        .ta-center { text-align: center; }
        .ta-right { text-align: right; }
        .insider-num {
          font-family: var(--font-display);
          color: var(--text-primary);
          white-space: nowrap;
        }
        .val-buy { color: var(--color-buy); }
        .val-sell { color: var(--color-sell); }
        .insider-date {
          font-family: var(--font-display);
          color: var(--text-primary);
          white-space: nowrap;
        }
        .insider-person {
          color: var(--text-primary);
          font-weight: 600;
        }
        .insider-role {
          font-size: 10px;
          color: var(--text-muted);
          margin-top: 2px;
        }
        .insider-reason {
          color: var(--text-muted);
          font-size: 10px;
          font-style: italic;
          max-width: 180px;
        }
        .insider-badge {
          display: inline-block;
          padding: 2px 8px;
          border-radius: 4px;
          font-size: 10px;
          font-weight: 700;
          letter-spacing: 0.5px;
        }
        .insider-badge.buy {
          background: rgba(34, 197, 94, 0.12);
          color: var(--color-buy);
          border: 1px solid rgba(34, 197, 94, 0.3);
        }
        .insider-badge.sell {
          background: rgba(244, 63, 94, 0.12);
          color: var(--color-sell);
          border: 1px solid rgba(244, 63, 94, 0.3);
        }
      `}</style>
    </div>
  );
}
