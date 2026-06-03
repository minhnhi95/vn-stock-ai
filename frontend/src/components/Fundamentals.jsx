import React from 'react';
import { FileText } from 'lucide-react';

const fmt = (v, suffix = '', prec = 2) => {
  if (v === null || v === undefined || Number.isNaN(v)) return 'N/A';
  return `${Number(v).toFixed(prec)}${suffix}`;
};

const Metric = ({ label, value, hint, tone }) => (
  <div className="fundamental-metric">
    <span className="fundamental-label">{label}</span>
    <span className={`fundamental-value ${tone || ''}`}>{value}</span>
    {hint ? <span className="fundamental-hint">{hint}</span> : null}
  </div>
);

const toneForPE = (pe) => {
  if (pe === null || pe === undefined) return '';
  if (pe < 10) return 'good';
  if (pe < 20) return 'neutral';
  return 'warn';
};
const toneForROE = (roe) => {
  if (roe === null || roe === undefined) return '';
  if (roe >= 15) return 'good';
  if (roe >= 8) return 'neutral';
  return 'warn';
};
const toneForGrowth = (g) => {
  if (g === null || g === undefined) return '';
  if (g > 10) return 'good';
  if (g >= 0) return 'neutral';
  return 'warn';
};

export default function Fundamentals({ data, symbol }) {
  const available = data?.available;

  return (
    <div className="glass-panel">
      <div className="panel-header">
        <div className="panel-title">
          <FileText size={16} className="text-accent" />
          <span>Cơ bản doanh nghiệp: {symbol}</span>
        </div>
        {data?.source ? <span className="fundamental-source">Nguồn: {data.source}</span> : null}
      </div>
      <div className="panel-content fundamental-grid">
        {!available ? (
          <div className="fundamental-empty">
            {data?.reason || 'Đang tải dữ liệu cơ bản...'}
          </div>
        ) : (
          <>
            <Metric label="P/E" value={fmt(data.pe)} tone={toneForPE(data.pe)} hint="< 10: rẻ · 10-20: hợp lý · > 20: cao" />
            <Metric label="P/B" value={fmt(data.pb)} />
            <Metric label="ROE" value={fmt(data.roe, '%')} tone={toneForROE(data.roe)} hint="> 15% tốt" />
            <Metric label="ROA" value={fmt(data.roa, '%')} />
            <Metric label="Net margin" value={fmt(data.net_margin, '%')} />
            <Metric label="Gross margin" value={fmt(data.gross_margin, '%')} />
            <Metric label="Nợ/VCSH" value={fmt(data.debt_to_equity)} />
            <Metric label="Cổ tức" value={fmt(data.dividend_yield, '%')} />
            <Metric label="EPS" value={fmt(data.eps, '', 0)} />
            {data.period ? <div className="fundamental-period">Kỳ: {data.period}</div> : null}
          </>
        )}
      </div>

      <style>{`
        .fundamental-grid {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 10px;
        }
        .fundamental-empty {
          grid-column: 1 / -1;
          padding: 20px 10px;
          text-align: center;
          color: var(--text-muted);
          font-size: 12px;
        }
        .fundamental-source {
          font-size: 10px;
          color: var(--text-muted);
        }
        .fundamental-metric {
          background: rgba(0, 0, 0, 0.25);
          border: 1px solid var(--border-color);
          border-radius: 8px;
          padding: 8px 10px;
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .fundamental-label {
          font-size: 10px;
          color: var(--text-muted);
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .fundamental-value {
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 14px;
          color: var(--text-primary);
        }
        .fundamental-value.good { color: var(--color-buy); }
        .fundamental-value.warn { color: var(--color-sell); }
        .fundamental-value.neutral { color: var(--color-accent); }
        .fundamental-hint {
          font-size: 9px;
          color: var(--text-muted);
        }
        .fundamental-period {
          grid-column: 1 / -1;
          text-align: center;
          font-size: 10px;
          color: var(--text-muted);
          padding: 4px;
          font-style: italic;
        }
      `}</style>
    </div>
  );
}
