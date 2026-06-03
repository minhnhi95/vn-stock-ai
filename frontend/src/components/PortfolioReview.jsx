import React, { useEffect, useState } from 'react';
import {
  X,
  Shield,
  AlertTriangle,
  TrendingUp,
  Sparkles,
  PieChart,
  Activity,
  Layers,
  Briefcase,
  Lightbulb,
  Loader2,
} from 'lucide-react';

const scoreTone = (score) => {
  if (score === null || score === undefined) return '';
  if (score >= 70) return 'good';
  if (score >= 40) return 'neutral';
  return 'bad';
};

const riskTone = (level) => {
  const v = (level || '').toUpperCase();
  if (v === 'LOW') return 'good';
  if (v === 'MEDIUM') return 'neutral';
  if (v === 'HIGH') return 'bad';
  return '';
};

const riskLabel = (level) => {
  const v = (level || '').toUpperCase();
  if (v === 'LOW') return 'Rủi ro thấp';
  if (v === 'MEDIUM') return 'Rủi ro trung bình';
  if (v === 'HIGH') return 'Rủi ro cao';
  return level || 'N/A';
};

const WARNING_META = {
  concentration: { icon: PieChart, label: 'Tập trung danh mục' },
  sector: { icon: Layers, label: 'Tập trung ngành' },
  correlation: { icon: Activity, label: 'Tương quan cao' },
};

export default function PortfolioReview({ apiBase, apiKey, open, onClose }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [review, setReview] = useState(null);
  const [empty, setEmpty] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;

    const run = async () => {
      setLoading(true);
      setError(null);
      setReview(null);
      setEmpty(false);
      try {
        const res = await fetch(`${apiBase}/api/portfolio/review`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ api_key: apiKey }),
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        if (cancelled) return;
        if (data?.empty || data?.is_empty || data?.holdings_count === 0) {
          setEmpty(true);
        } else {
          setReview(data);
        }
      } catch (e) {
        if (!cancelled) setError(e.message || 'Lỗi khi phân tích danh mục');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    run();
    return () => { cancelled = true; };
  }, [open, apiBase, apiKey]);

  if (!open) return null;

  const score = review?.overall_score;
  const sTone = scoreTone(score);
  const rTone = riskTone(review?.risk_level);
  const warnings = review?.warnings || {};
  const activeWarnings = Object.keys(WARNING_META).filter((k) => {
    const w = warnings[k];
    if (!w) return false;
    if (typeof w === 'object') return w.triggered || w.severity || w.message;
    return Boolean(w);
  });
  const rebalance = review?.rebalance_suggestions || review?.suggestions || [];

  return (
    <div className="pr-backdrop" onClick={onClose}>
      <div className="pr-modal glass-panel" onClick={(e) => e.stopPropagation()}>
        <div className="pr-header">
          <div className="panel-title">
            <Sparkles size={18} className="logo-icon" />
            <span>Phân tích danh mục</span>
          </div>
          <button className="pr-close" onClick={onClose} aria-label="Đóng">
            <X size={18} />
          </button>
        </div>

        {loading && (
          <div className="pr-state">
            <Loader2 size={28} className="pr-spinner" />
            <div className="pr-state-title">AI đang phân tích danh mục của bạn</div>
            <div className="pr-state-sub">Đang đánh giá tập trung, ngành nghề, tương quan...</div>
          </div>
        )}

        {!loading && error && (
          <div className="pr-error">
            <AlertTriangle size={14} /> {error}
          </div>
        )}

        {!loading && !error && empty && (
          <div className="pr-state">
            <Briefcase size={28} className="pr-empty-icon" />
            <div className="pr-state-title">Danh mục trống</div>
            <div className="pr-state-sub">
              Bạn chưa nắm giữ cổ phiếu nào — mua mã trước rồi xem review.
            </div>
          </div>
        )}

        {!loading && !error && review && (
          <div className="pr-body">
            <div className="pr-summary">
              <div className={`pr-score pr-score-${sTone}`}>
                <span className="pr-score-label">Điểm tổng</span>
                <span className="pr-score-value">
                  {score === null || score === undefined ? 'N/A' : Math.round(score)}
                </span>
                <span className="pr-score-max">/ 100</span>
              </div>
              <div className="pr-risk">
                <span className="pr-risk-label">
                  <Shield size={12} /> Mức rủi ro
                </span>
                <span className={`pr-risk-badge pr-risk-${rTone}`}>
                  {riskLabel(review.risk_level)}
                </span>
              </div>
            </div>

            {activeWarnings.length > 0 && (
              <div className="pr-section">
                <div className="pr-section-title">
                  <AlertTriangle size={13} /> Cảnh báo
                </div>
                <div className="pr-warnings">
                  {activeWarnings.map((key) => {
                    const meta = WARNING_META[key];
                    const Icon = meta.icon;
                    const w = warnings[key] || {};
                    const severity = (w.severity || '').toLowerCase();
                    const msg = typeof w === 'string'
                      ? w
                      : (w.message || w.detail || w.description || '');
                    return (
                      <div key={key} className={`pr-warning pr-warning-${severity || 'medium'}`}>
                        <div className="pr-warning-head">
                          <Icon size={14} />
                          <span className="pr-warning-label">{meta.label}</span>
                          {severity && (
                            <span className={`pr-warning-sev pr-warning-sev-${severity}`}>
                              {severity.toUpperCase()}
                            </span>
                          )}
                        </div>
                        {msg && <div className="pr-warning-msg">{msg}</div>}
                        {w.metric !== undefined && w.metric !== null && (
                          <div className="pr-warning-metric">
                            {w.metric_label || 'Chỉ số'}: <strong>{w.metric}</strong>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {review.recommendation && (
              <div className="pr-section">
                <div className="pr-section-title">
                  <Lightbulb size={13} /> Khuyến nghị
                </div>
                <div className="pr-recommendation">{review.recommendation}</div>
              </div>
            )}

            {rebalance.length > 0 && (
              <div className="pr-section">
                <div className="pr-section-title">
                  <TrendingUp size={13} /> Đề xuất tái cân bằng
                </div>
                <ul className="pr-rebalance">
                  {rebalance.map((s, i) => (
                    <li key={i} className="pr-rebalance-item">
                      {typeof s === 'string' ? s : (s.text || s.message || s.action || JSON.stringify(s))}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      <style>{`
        .pr-backdrop {
          position: fixed; inset: 0; z-index: 200;
          background: rgba(2, 6, 23, 0.7);
          backdrop-filter: blur(4px);
          display: flex; align-items: center; justify-content: center;
          animation: pr-fade-in 0.2s ease-out;
        }
        @keyframes pr-fade-in { from { opacity: 0; } to { opacity: 1; } }
        @keyframes pr-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }

        .pr-modal {
          width: min(720px, 94vw);
          max-height: 92vh;
          padding: 18px 22px;
          display: flex; flex-direction: column;
          overflow-y: auto;
        }
        .pr-header {
          display: flex; align-items: center; justify-content: space-between;
          margin-bottom: 16px;
        }
        .pr-close {
          background: transparent; border: none; color: var(--text-muted);
          cursor: pointer; padding: 4px; border-radius: 6px;
        }
        .pr-close:hover { color: var(--text-primary); background: rgba(255,255,255,0.05); }

        .pr-state {
          display: flex; flex-direction: column; align-items: center; justify-content: center;
          padding: 48px 20px;
          gap: 10px;
          text-align: center;
        }
        .pr-spinner {
          color: var(--color-accent);
          animation: pr-spin 1s linear infinite;
        }
        .pr-empty-icon { color: var(--text-muted); }
        .pr-state-title {
          font-size: 14px; color: var(--text-primary); font-weight: 600;
          margin-top: 6px;
        }
        .pr-state-sub {
          font-size: 12px; color: var(--text-muted);
          max-width: 320px; line-height: 1.5;
        }

        .pr-error {
          display: flex; align-items: center; gap: 8px;
          background: rgba(244,63,94,0.12);
          border: 1px solid rgba(244,63,94,0.4);
          color: #ffd9e0;
          padding: 10px 14px; border-radius: 8px;
          font-size: 12px;
        }

        .pr-body {
          display: flex; flex-direction: column; gap: 18px;
        }

        .pr-summary {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 12px;
        }
        .pr-score {
          background: rgba(0,0,0,0.25);
          border: 1px solid var(--border-color);
          border-radius: 10px;
          padding: 14px 16px;
          display: flex; flex-direction: column; align-items: flex-start;
          gap: 2px;
          position: relative;
          overflow: hidden;
        }
        .pr-score::before {
          content: '';
          position: absolute; left: 0; top: 0; bottom: 0;
          width: 3px;
          background: var(--text-muted);
        }
        .pr-score-good::before { background: var(--color-buy); }
        .pr-score-neutral::before { background: #f59e0b; }
        .pr-score-bad::before { background: var(--color-sell); }
        .pr-score-label {
          font-size: 10px; color: var(--text-muted); text-transform: uppercase;
          letter-spacing: 0.3px;
        }
        .pr-score-value {
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 48px;
          line-height: 1;
          color: var(--text-primary);
        }
        .pr-score-good .pr-score-value { color: var(--color-buy); }
        .pr-score-neutral .pr-score-value { color: #fbbf24; }
        .pr-score-bad .pr-score-value { color: var(--color-sell); }
        .pr-score-max {
          font-size: 11px; color: var(--text-muted);
          margin-top: 2px;
        }

        .pr-risk {
          background: rgba(0,0,0,0.25);
          border: 1px solid var(--border-color);
          border-radius: 10px;
          padding: 14px 16px;
          display: flex; flex-direction: column;
          gap: 10px;
          justify-content: center;
        }
        .pr-risk-label {
          font-size: 10px; color: var(--text-muted); text-transform: uppercase;
          letter-spacing: 0.3px;
          display: inline-flex; align-items: center; gap: 5px;
        }
        .pr-risk-badge {
          align-self: flex-start;
          padding: 6px 12px;
          border-radius: 999px;
          font-size: 12px;
          font-weight: 700;
          font-family: var(--font-display);
          background: rgba(148,163,184,0.12);
          color: var(--text-secondary);
          border: 1px solid var(--border-color);
        }
        .pr-risk-good {
          background: rgba(16,185,129,0.12);
          color: var(--color-buy);
          border-color: rgba(16,185,129,0.35);
        }
        .pr-risk-neutral {
          background: rgba(245,158,11,0.12);
          color: #fbbf24;
          border-color: rgba(245,158,11,0.35);
        }
        .pr-risk-bad {
          background: rgba(244,63,94,0.12);
          color: var(--color-sell);
          border-color: rgba(244,63,94,0.35);
        }

        .pr-section {
          display: flex; flex-direction: column; gap: 8px;
        }
        .pr-section-title {
          display: inline-flex; align-items: center; gap: 6px;
          font-size: 11px;
          color: var(--text-secondary);
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.4px;
        }

        .pr-warnings {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 10px;
        }
        .pr-warning {
          background: rgba(0,0,0,0.25);
          border: 1px solid var(--border-color);
          border-left: 3px solid #f59e0b;
          border-radius: 8px;
          padding: 10px 12px;
          display: flex; flex-direction: column; gap: 6px;
        }
        .pr-warning-high { border-left-color: var(--color-sell); }
        .pr-warning-medium { border-left-color: #f59e0b; }
        .pr-warning-low { border-left-color: var(--color-accent); }
        .pr-warning-head {
          display: flex; align-items: center; gap: 6px;
          color: var(--text-primary);
        }
        .pr-warning-label {
          font-size: 12px;
          font-weight: 600;
          flex: 1;
        }
        .pr-warning-sev {
          font-size: 9px;
          font-weight: 700;
          padding: 2px 6px;
          border-radius: 4px;
          letter-spacing: 0.4px;
          font-family: var(--font-display);
        }
        .pr-warning-sev-high {
          background: rgba(244,63,94,0.15);
          color: var(--color-sell);
        }
        .pr-warning-sev-medium {
          background: rgba(245,158,11,0.15);
          color: #fbbf24;
        }
        .pr-warning-sev-low {
          background: rgba(6,182,212,0.15);
          color: var(--color-accent);
        }
        .pr-warning-msg {
          font-size: 11px;
          color: var(--text-secondary);
          line-height: 1.5;
        }
        .pr-warning-metric {
          font-size: 10px;
          color: var(--text-muted);
          font-family: var(--font-display);
        }
        .pr-warning-metric strong {
          color: var(--text-primary);
          font-weight: 700;
        }

        .pr-recommendation {
          background: rgba(6,182,212,0.06);
          border: 1px solid rgba(6,182,212,0.2);
          border-radius: 8px;
          padding: 12px 14px;
          font-size: 12px;
          color: var(--text-primary);
          line-height: 1.6;
        }

        .pr-rebalance {
          list-style: none;
          padding: 0;
          margin: 0;
          display: flex; flex-direction: column; gap: 6px;
        }
        .pr-rebalance-item {
          background: rgba(0,0,0,0.2);
          border: 1px solid var(--border-color);
          border-radius: 6px;
          padding: 8px 12px 8px 28px;
          font-size: 12px;
          color: var(--text-secondary);
          line-height: 1.5;
          position: relative;
        }
        .pr-rebalance-item::before {
          content: '';
          position: absolute;
          left: 12px;
          top: 14px;
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: var(--color-accent);
        }
      `}</style>
    </div>
  );
}
