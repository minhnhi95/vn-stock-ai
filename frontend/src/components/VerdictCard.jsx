import { useCallback, useEffect, useState } from 'react';
import { Target, RefreshCw, Check, X, HelpCircle, History } from 'lucide-react';

/**
 * Kết luận có thể cân nhắc mua / chờ thêm / không nên mua cho mã đang xem.
 *
 * Kết luận đến từ quy tắc cố định ở backend (verdict_engine.py), không phải từ AI:
 * từng tiêu chí hiện kèm con số và ngưỡng, và luôn có tỷ lệ quy tắc từng đúng trong
 * quá khứ với chính mã này — để người dùng biết nên tin kết luận tới đâu.
 */

const VERDICT_CLASS = { buy_consider: 'vd-buy', wait: 'vd-wait', avoid: 'vd-avoid' };
const STATUS_ICON = { pass: Check, fail: X, unknown: HelpCircle };
const GROUPS = [
  { key: 'an_toan', label: 'An toàn' },
  { key: 'xu_huong', label: 'Xu hướng giá' },
  { key: 'nen_tang', label: 'Nền tảng doanh nghiệp' },
];

export default function VerdictCard({ apiBase, symbol }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    if (!apiBase || !symbol) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/verdict?symbol=${encodeURIComponent(symbol)}`);
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`);
      setData(json);
    } catch (err) {
      setError(err.message || 'Không tính được kết luận');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [apiBase, symbol]);

  useEffect(() => {
    load();
  }, [load]);

  const checks = data?.checks || [];
  const history = data?.history;

  return (
    <div className="glass-panel">
      <div className="panel-header">
        <div className="panel-title">
          <Target size={16} className="text-accent" />
          <span>Kết luận: {symbol}</span>
        </div>
        <button type="button" className="vd-refresh" onClick={load} disabled={loading} title="Tính lại">
          <RefreshCw size={12} className={loading ? 'spin' : ''} />
        </button>
      </div>

      <div className="panel-content vd-content">
        {error ? <div className="vd-error">{error}</div> : null}
        {loading && !data ? <div className="vd-loading">Đang tính kết luận...</div> : null}

        {data ? (
          <>
            <div className={`vd-verdict ${VERDICT_CLASS[data.verdict] || 'vd-wait'}`}>
              <span className="vd-label">{data.label}</span>
              <span className="vd-headline">{data.headline}</span>
            </div>

            {data.data_gaps?.map((gap) => (
              <div key={gap} className="vd-gap">{gap}</div>
            ))}

            {GROUPS.map((group) => {
              const rows = checks.filter((c) => c.group === group.key);
              if (!rows.length) return null;
              return (
                <div key={group.key} className="vd-group">
                  <div className="vd-group-title">{group.label}</div>
                  {rows.map((c) => {
                    const Icon = STATUS_ICON[c.status] || HelpCircle;
                    return (
                      <div key={c.key} className={`vd-row vd-${c.status}`}>
                        <Icon size={13} className="vd-icon" />
                        <span className="vd-row-label">{c.label}</span>
                        <span className="vd-row-value">{c.display || 'Thiếu dữ liệu'}</span>
                        <span className="vd-row-threshold">Cần: {c.threshold}</span>
                      </div>
                    );
                  })}
                </div>
              );
            })}

            <div className={`vd-history vd-edge-${history?.edge || 'none'}`}>
              <div className="vd-group-title">
                <History size={12} /> Quy tắc này từng đúng tới đâu với {data.symbol}?
              </div>
              {history?.available ? (
                <>
                  <p className="vd-summary">{history.summary}</p>
                  <p className="vd-note">
                    Đo trên khoảng 2 năm dữ liệu. Các phiên liền nhau chồng thời gian lên nhau, nên
                    số lần thực sự độc lập ít hơn con số trên. Chỉ so phần kỹ thuật vì không có lịch
                    sử chỉ số cơ bản theo từng phiên.
                  </p>
                </>
              ) : (
                <p>{history?.reason || 'Chưa đo được.'}</p>
              )}
            </div>

            <p className="vd-rule">{data.rule}</p>
            <p className="vd-disclaimer">{data.disclaimer}</p>
          </>
        ) : null}
      </div>

      <style>{`
        .vd-refresh {
          background: none;
          border: 1px solid var(--border-color);
          border-radius: 999px;
          color: var(--text-muted);
          cursor: pointer;
          padding: 4px 7px;
          display: inline-flex;
        }
        .vd-content { gap: 10px; }
        .vd-error { font-size: 11px; color: var(--color-sell); }
        .vd-gap { font-size: 11px; color: var(--color-hold, #f59e0b); }
        .vd-loading { font-size: 12px; color: var(--text-muted); text-align: center; padding: 12px; }
        .vd-verdict {
          display: flex;
          flex-direction: column;
          gap: 4px;
          padding: 12px 14px;
          border-radius: 10px;
          border: 1px solid var(--border-color);
        }
        .vd-label {
          font-family: var(--font-display);
          font-size: 17px;
          font-weight: 700;
        }
        .vd-headline { font-size: 11.5px; line-height: 1.5; color: var(--text-primary); }
        .vd-buy { background: rgba(16, 185, 129, 0.12); border-color: rgba(16, 185, 129, 0.45); }
        .vd-buy .vd-label { color: var(--color-buy); }
        .vd-wait { background: rgba(245, 158, 11, 0.1); border-color: rgba(245, 158, 11, 0.4); }
        .vd-wait .vd-label { color: var(--color-hold, #f59e0b); }
        .vd-avoid { background: rgba(244, 63, 94, 0.1); border-color: rgba(244, 63, 94, 0.45); }
        .vd-avoid .vd-label { color: var(--color-sell); }
        .vd-group { display: flex; flex-direction: column; gap: 4px; }
        .vd-group-title {
          display: flex;
          align-items: center;
          gap: 5px;
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          color: var(--text-muted);
        }
        .vd-row {
          display: grid;
          grid-template-columns: 16px 1fr auto;
          column-gap: 8px;
          row-gap: 2px;
          align-items: center;
          padding: 7px 10px;
          border: 1px solid var(--border-color);
          border-radius: 7px;
          background: rgba(0, 0, 0, 0.2);
          font-size: 11px;
        }
        .vd-row-label { color: var(--text-primary); }
        .vd-row-value {
          font-family: var(--font-display);
          font-weight: 600;
          font-variant-numeric: tabular-nums;
          white-space: nowrap;
          color: var(--text-muted);
        }
        .vd-row-threshold { grid-column: 2 / -1; font-size: 10px; color: var(--text-muted); }
        .vd-pass .vd-icon { color: var(--color-buy); }
        .vd-fail .vd-icon, .vd-fail .vd-row-value { color: var(--color-sell); }
        .vd-unknown .vd-icon { color: var(--text-muted); }
        .vd-history {
          display: flex;
          flex-direction: column;
          gap: 6px;
          padding: 10px 12px;
          border-radius: 8px;
          background: rgba(255, 255, 255, 0.02);
          border: 1px dashed var(--border-color);
        }
        .vd-history p { margin: 0; font-size: 11.5px; line-height: 1.6; color: var(--text-secondary); }
        .vd-history .vd-note { font-size: 10px; color: var(--text-muted); }
        .vd-edge-better { border-color: rgba(16, 185, 129, 0.45); }
        .vd-edge-worse { border-color: rgba(244, 63, 94, 0.5); }
        .vd-edge-worse .vd-summary { color: var(--color-sell); }
        .vd-rule, .vd-disclaimer { margin: 0; font-size: 10px; line-height: 1.5; color: var(--text-muted); }
      `}</style>
    </div>
  );
}
