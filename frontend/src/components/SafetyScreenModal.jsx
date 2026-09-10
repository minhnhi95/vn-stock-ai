import { useCallback, useEffect, useState } from 'react';
import { X, ShieldCheck, ShieldAlert, HelpCircle, RefreshCw } from 'lucide-react';
import useModalDismiss from '../hooks/useModalDismiss';

/**
 * Quét bộ lọc an toàn cho nhiều mã cùng lúc.
 *
 * Thay cho "AI Scanner" cũ vốn chấm điểm 0-100 và xếp hạng cơ hội. Với người
 * mới, một bảng xếp hạng có điểm số chính là danh sách gợi ý mua — thứ mà mô
 * hình không đủ căn cứ để đưa ra. Bảng này chỉ trả lời một câu hỏi hẹp và trả
 * lời được: "mã nào trong danh sách có dấu hiệu rủi ro cơ bản?"
 *
 * Sắp xếp: nhiều cảnh báo lên trước, vì đó là thứ cần xem, không phải thứ "tốt nhất".
 */

const VERDICT = {
  caution: { Icon: ShieldAlert, cls: 'ss-caution', text: 'Cần cân nhắc' },
  incomplete: { Icon: HelpCircle, cls: 'ss-incomplete', text: 'Thiếu dữ liệu' },
  basic_ok: { Icon: ShieldCheck, cls: 'ss-ok', text: 'Qua bộ lọc' },
};

export default function SafetyScreenModal({ apiBase, open, onClose, onSelectSymbol }) {
  useModalDismiss(open, onClose);

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [input, setInput] = useState('');

  const run = useCallback(
    async (symbols) => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${apiBase}/safety/screen`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbols: symbols && symbols.length ? symbols : null }),
        });
        const json = await res.json();
        if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`);
        setData(json);
      } catch (err) {
        setError(err.message || 'Quét thất bại');
      } finally {
        setLoading(false);
      }
    },
    [apiBase],
  );

  useEffect(() => {
    // Mở lên là quét luôn danh mục thật (backend tự lấy), khỏi bắt bấm thêm.
    if (open && !data) run(null);
  }, [open, data, run]);

  if (!open) return null;

  const submit = (event) => {
    event.preventDefault();
    const symbols = input
      .split(/[\s,;]+/)
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean);
    run(symbols);
  };

  const results = data?.results || [];

  return (
    <div className="ss-backdrop" onClick={onClose}>
      <div className="ss-modal glass-panel" onClick={(e) => e.stopPropagation()}>
        <div className="ss-header">
          <div className="panel-title">
            <ShieldCheck size={18} className="logo-icon" />
            <span>Kiểm tra an toàn nhiều mã</span>
          </div>
          <button className="ss-close" onClick={onClose} aria-label="Đóng">
            <X size={18} />
          </button>
        </div>

        <p className="ss-intro">
          Bộ lọc này <b>không tìm mã tốt</b> — nó chỉ ra mã có dấu hiệu rủi ro cơ bản:
          thanh khoản thấp, thị giá quá nhỏ, nợ cao, đang lỗ. Bỏ trống ô dưới để quét
          danh mục thật của bạn.
        </p>

        <form className="ss-form" onSubmit={submit}>
          <input
            type="text"
            placeholder="FPT HPG VNM (cách nhau bằng dấu cách)"
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
          <button type="submit" className="btn btn-outline ss-run" disabled={loading}>
            <RefreshCw size={13} className={loading ? 'spin' : ''} />
            <span>{loading ? 'Đang quét...' : 'Quét'}</span>
          </button>
        </form>

        {error ? <div className="ss-error">{error}</div> : null}

        <div className="ss-results">
          {results.map((item) => {
            const meta = VERDICT[item.verdict] || VERDICT.incomplete;
            const MetaIcon = meta.Icon;
            const problems = item.checks.filter((c) => c.status === 'fail');
            return (
              <div key={item.symbol} className={`ss-row ${meta.cls}`}>
                <div className="ss-row-top">
                  <button
                    type="button"
                    className="ss-symbol"
                    onClick={() => {
                      onSelectSymbol?.(item.symbol);
                      onClose();
                    }}
                  >
                    {item.symbol}
                  </button>
                  <span className="ss-verdict">
                    <MetaIcon size={12} />
                    {meta.text}
                  </span>
                </div>
                {problems.length ? (
                  <ul className="ss-problems">
                    {problems.map((p) => (
                      <li key={p.key}>
                        <span className="ss-p-label">{p.label}</span>
                        <span className="ss-p-value">{p.display || '—'}</span>
                        <span className="ss-p-threshold">cần {p.threshold}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="ss-clean">{item.headline}</div>
                )}
              </div>
            );
          })}
          {!loading && !results.length && !error ? (
            <div className="ss-empty">Chưa có kết quả.</div>
          ) : null}
        </div>

        {data?.errors?.length ? (
          <div className="ss-warn">
            Không lấy được dữ liệu cho: {data.errors.map((e) => e.symbol).join(', ')}
          </div>
        ) : null}
      </div>

      <style>{`
        .ss-backdrop {
          position: fixed;
          inset: 0;
          z-index: 200;
          background: rgba(2, 5, 12, 0.75);
          backdrop-filter: blur(4px);
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 16px;
        }
        .ss-modal {
          width: min(680px, 100%);
          max-height: min(85vh, 760px);
          overflow-y: auto;
          padding: 18px;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .ss-header { display: flex; align-items: center; justify-content: space-between; }
        .ss-close {
          background: none;
          border: none;
          color: var(--text-muted);
          cursor: pointer;
          padding: 4px;
        }
        .ss-intro {
          margin: 0;
          font-size: 11px;
          line-height: 1.6;
          color: var(--text-muted);
        }
        .ss-intro b { color: var(--text-primary); }
        .ss-form { display: flex; gap: 8px; }
        .ss-form input {
          flex: 1 1 auto;
          min-width: 0;
          background: rgba(0, 0, 0, 0.3);
          border: 1px solid var(--border-color);
          border-radius: 7px;
          padding: 9px 11px;
          color: var(--text-primary);
          font-size: 13px;
        }
        .ss-run { display: flex; align-items: center; gap: 6px; font-size: 12px; padding: 8px 14px; }
        .ss-error { font-size: 11px; color: var(--color-sell); }
        .ss-results { display: flex; flex-direction: column; gap: 8px; }
        .ss-row {
          border: 1px solid var(--border-color);
          border-left-width: 3px;
          border-radius: 8px;
          background: rgba(0, 0, 0, 0.22);
          padding: 10px 12px;
        }
        .ss-caution { border-left-color: var(--color-sell); }
        .ss-ok { border-left-color: var(--color-buy); }
        .ss-incomplete { border-left-color: var(--text-muted); }
        .ss-row-top { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
        .ss-symbol {
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 14px;
          color: var(--color-accent);
          background: none;
          border: none;
          cursor: pointer;
          padding: 0;
        }
        .ss-symbol:hover { text-decoration: underline; }
        .ss-verdict {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          font-size: 10px;
          color: var(--text-muted);
        }
        .ss-caution .ss-verdict { color: var(--color-sell); }
        .ss-ok .ss-verdict { color: var(--color-buy); }
        .ss-problems { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
        .ss-problems li {
          display: grid;
          grid-template-columns: 1fr auto auto;
          gap: 8px;
          align-items: baseline;
          font-size: 11px;
        }
        .ss-p-label { color: var(--text-primary); }
        .ss-p-value {
          font-family: var(--font-display);
          font-weight: 600;
          color: var(--color-sell);
          font-variant-numeric: tabular-nums;
        }
        .ss-p-threshold { font-size: 10px; color: var(--text-muted); white-space: nowrap; }
        .ss-clean { margin-top: 6px; font-size: 11px; color: var(--text-muted); }
        .ss-empty, .ss-warn { font-size: 11px; color: var(--text-muted); text-align: center; padding: 8px; }
      `}</style>
    </div>
  );
}
