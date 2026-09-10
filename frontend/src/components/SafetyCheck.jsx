import { useCallback, useEffect, useState } from 'react';
import { ShieldCheck, ShieldAlert, RefreshCw, Check, X, HelpCircle } from 'lucide-react';

/**
 * Bộ lọc an toàn cho mã đang xem.
 *
 * Cố ý KHÔNG hiện điểm tổng và không hiện nhãn mua/bán. Người mới cần biết
 * mình đang chịu rủi ro CỤ THỂ nào, kèm con số để tự đối chiếu — chứ không phải
 * một số "78/100" mà họ không truy được nguồn.
 *
 * "unknown" hiển thị khác hẳn "pass": thiếu dữ liệu không phải là an toàn.
 */

const STATUS_META = {
  pass: { Icon: Check, cls: 'sc-pass', label: 'Đạt' },
  fail: { Icon: X, cls: 'sc-fail', label: 'Cần cân nhắc' },
  unknown: { Icon: HelpCircle, cls: 'sc-unknown', label: 'Thiếu dữ liệu' },
};

const VERDICT_META = {
  basic_ok: { Icon: ShieldCheck, cls: 'sc-verdict-ok' },
  incomplete: { Icon: HelpCircle, cls: 'sc-verdict-partial' },
  caution: { Icon: ShieldAlert, cls: 'sc-verdict-caution' },
};

export default function SafetyCheck({ apiBase, symbol }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(null);

  const load = useCallback(async () => {
    if (!apiBase || !symbol) return;
    setLoading(true);
    setError(null);
    setExpanded(null);
    try {
      const res = await fetch(`${apiBase}/safety?symbol=${encodeURIComponent(symbol)}`);
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`);
      setData(json);
    } catch (err) {
      setError(err.message || 'Không kiểm tra được');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [apiBase, symbol]);

  useEffect(() => {
    load();
  }, [load]);

  const verdict = VERDICT_META[data?.verdict] || VERDICT_META.incomplete;
  const VerdictIcon = verdict.Icon;
  const checks = data?.checks || [];

  return (
    <div className="glass-panel">
      <div className="panel-header">
        <div className="panel-title">
          <ShieldCheck size={16} className="text-accent" />
          <span>Kiểm tra an toàn: {symbol}</span>
        </div>
        <button type="button" className="sc-refresh" onClick={load} disabled={loading} title="Kiểm tra lại">
          <RefreshCw size={12} className={loading ? 'spin' : ''} />
        </button>
      </div>

      <div className="panel-content sc-content">
        {error ? <div className="sc-error">{error}</div> : null}
        {loading && !data ? <div className="sc-loading">Đang kiểm tra...</div> : null}

        {data ? (
          <>
            <div className={`sc-verdict ${verdict.cls}`}>
              <VerdictIcon size={16} />
              <span>{data.headline}</span>
            </div>

            <div className="sc-list">
              {checks.map((check) => {
                const meta = STATUS_META[check.status] || STATUS_META.unknown;
                const StatusIcon = meta.Icon;
                const open = expanded === check.key;
                // Chỉ mục "cần cân nhắc" và "thiếu dữ liệu" mới bấm mở được —
                // mục đạt thì không có gì để giải thích thêm.
                const clickable = check.status !== 'pass';
                return (
                  <div key={check.key} className={`sc-row ${meta.cls} ${open ? 'open' : ''}`}>
                    <button
                      type="button"
                      className="sc-row-head"
                      onClick={() => clickable && setExpanded(open ? null : check.key)}
                      disabled={!clickable}
                    >
                      <StatusIcon size={13} className="sc-icon" />
                      <span className="sc-label">{check.label}</span>
                      <span className="sc-value">{check.display || '—'}</span>
                    </button>
                    {open ? (
                      <div className="sc-detail">
                        <p>{check.explain}</p>
                        <span className="sc-threshold">Ngưỡng an toàn: {check.threshold}</span>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>

            <p className="sc-disclaimer">{data.disclaimer}</p>
          </>
        ) : null}
      </div>

      <style>{`
        .sc-refresh {
          background: none;
          border: 1px solid var(--border-color);
          border-radius: 999px;
          color: var(--text-muted);
          cursor: pointer;
          padding: 4px 7px;
          display: inline-flex;
        }
        .sc-content { gap: 10px; }
        .sc-error { font-size: 11px; color: var(--color-sell); }
        .sc-loading { font-size: 12px; color: var(--text-muted); text-align: center; padding: 12px; }
        .sc-verdict {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 12px;
          font-weight: 600;
          padding: 9px 11px;
          border-radius: 8px;
          line-height: 1.4;
        }
        .sc-verdict-ok {
          background: rgba(16, 185, 129, 0.1);
          border: 1px solid rgba(16, 185, 129, 0.3);
          color: var(--color-buy);
        }
        .sc-verdict-caution {
          background: rgba(244, 63, 94, 0.1);
          border: 1px solid rgba(244, 63, 94, 0.3);
          color: var(--color-sell);
        }
        .sc-verdict-partial {
          background: rgba(148, 163, 184, 0.1);
          border: 1px solid var(--border-color);
          color: var(--text-muted);
        }
        .sc-list { display: flex; flex-direction: column; gap: 4px; }
        .sc-row {
          border: 1px solid var(--border-color);
          border-radius: 7px;
          background: rgba(0, 0, 0, 0.2);
          overflow: hidden;
        }
        .sc-row.open { border-color: rgba(244, 63, 94, 0.35); }
        .sc-row-head {
          width: 100%;
          display: grid;
          grid-template-columns: 16px 1fr auto;
          align-items: center;
          gap: 8px;
          padding: 8px 10px;
          background: none;
          border: none;
          color: inherit;
          text-align: left;
          font-size: 11px;
        }
        .sc-row-head:not(:disabled) { cursor: pointer; }
        .sc-row-head:disabled { opacity: 0.85; }
        .sc-pass .sc-icon { color: var(--color-buy); }
        .sc-fail .sc-icon { color: var(--color-sell); }
        .sc-unknown .sc-icon { color: var(--text-muted); }
        .sc-label { color: var(--text-primary); }
        .sc-value {
          font-family: var(--font-display);
          font-weight: 600;
          font-variant-numeric: tabular-nums;
          color: var(--text-muted);
          white-space: nowrap;
        }
        .sc-fail .sc-value { color: var(--color-sell); }
        .sc-detail {
          padding: 0 10px 10px 34px;
          font-size: 11px;
          line-height: 1.6;
          color: var(--text-muted);
        }
        .sc-detail p { margin: 0 0 5px; }
        .sc-threshold { font-size: 10px; opacity: 0.8; }
        .sc-disclaimer {
          margin: 0;
          font-size: 10px;
          line-height: 1.5;
          color: var(--text-muted);
          opacity: 0.8;
        }
      `}</style>
    </div>
  );
}
