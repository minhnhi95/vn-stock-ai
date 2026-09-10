import { useCallback, useEffect, useState } from 'react';
import { Newspaper, RefreshCw, Globe2, HelpCircle, AlertTriangle } from 'lucide-react';

/**
 * Bản tin sáng — chỉ ĐỌC từ DB.
 *
 * Nội dung do job nền sinh bằng Antigravity CLI. Panel này cố ý không có nút
 * "phân tích ngay": gọi AI mất ~60 giây, bắt người dùng ngồi chờ là thiết kế tệ.
 *
 * Cũng cố ý không có điểm số hay nhãn mua/bán — mục tiêu là giúp người mới HIỂU,
 * không phải đưa cho họ một mệnh lệnh mà họ không đủ nền để nghi ngờ.
 */

const fmtDate = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('vi-VN', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
};

const fmtChange = (v) => {
  if (v === null || v === undefined) return null;
  const n = Number(v);
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`;
};

const changeTone = (v) => {
  if (v === null || v === undefined || Number(v) === 0) return '';
  return Number(v) > 0 ? 'db-up' : 'db-down';
};

export default function DailyBrief({ apiBase, onSelectSymbol }) {
  const [brief, setBrief] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [openSymbol, setOpenSymbol] = useState(null);

  const load = useCallback(async () => {
    if (!apiBase) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/brief`);
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`);
      setBrief(json);
      // Mở sẵn mã đầu tiên để người dùng thấy ngay nội dung, khỏi phải bấm.
      const first = json?.content?.diem_tin?.[0]?.ma;
      if (first) setOpenSymbol(first);
    } catch (err) {
      setError(err.message || 'Không tải được bản tin');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    load();
  }, [load]);

  const content = brief?.content || {};
  const items = Array.isArray(content.diem_tin) ? content.diem_tin : [];
  const macro = Array.isArray(brief?.macro) ? brief.macro : [];

  return (
    <div className="glass-panel db-panel">
      <div className="panel-header">
        <div className="panel-title">
          <Newspaper size={16} className="text-accent" />
          <span>Bản tin sáng nay</span>
        </div>
        <div className="db-header-right">
          {brief?.generated_at ? (
            <span className="db-stamp">{fmtDate(brief.generated_at)}</span>
          ) : null}
          <button type="button" className="db-refresh" onClick={load} disabled={loading} title="Tải lại">
            <RefreshCw size={12} className={loading ? 'spin' : ''} />
          </button>
        </div>
      </div>

      <div className="panel-content db-content">
        {error ? <div className="db-error">{error}</div> : null}

        {!error && brief && brief.available === false ? (
          <div className="db-empty">
            <p>{brief.reason}</p>
            <code className="db-cmd">python -m jobs.daily_brief</code>
          </div>
        ) : null}

        {loading && !brief ? <div className="db-empty">Đang tải bản tin...</div> : null}

        {brief?.available ? (
          <>
            {content.tong_quan ? <p className="db-lead">{content.tong_quan}</p> : null}

            {macro.length ? (
              <div className="db-macro">
                <div className="db-macro-head">
                  <Globe2 size={11} />
                  <span>Thế giới đêm qua</span>
                </div>
                <div className="db-macro-grid">
                  {macro.map((m) => (
                    <div key={m.ticker} className="db-macro-item" title={m.transmission}>
                      <span className="db-macro-label">{m.label}</span>
                      <span className="db-macro-value">
                        {Number(m.value).toLocaleString()} {m.unit}
                      </span>
                      <span className={`db-macro-change ${changeTone(m.change_5d_pct)}`}>
                        {fmtChange(m.change_5d_pct) || '—'} <i>/5 phiên</i>
                      </span>
                    </div>
                  ))}
                </div>
                {content.boi_canh_the_gioi ? (
                  <p className="db-macro-note">{content.boi_canh_the_gioi}</p>
                ) : null}
              </div>
            ) : null}

            <div className="db-items">
              {items.map((item) => {
                const open = openSymbol === item.ma;
                return (
                  <div key={item.ma} className={`db-item ${open ? 'open' : ''}`}>
                    <button
                      type="button"
                      className="db-item-head"
                      onClick={() => setOpenSymbol(open ? null : item.ma)}
                    >
                      <span className="db-sym">{item.ma}</span>
                      <span className="db-item-teaser">{item.su_kien}</span>
                    </button>

                    {open ? (
                      <div className="db-item-body">
                        <dl className="db-fields">
                          <dt>Thị trường đã biết chưa?</dt>
                          <dd>{item.da_phan_anh}</dd>

                          <dt>Nếu tin này đúng thì sao?</dt>
                          <dd>{item.neu_dung_thi_sao}</dd>

                          <dt className="db-warn">
                            <AlertTriangle size={11} /> Điều gì làm nhận định này sai?
                          </dt>
                          <dd>{item.dieu_gi_lam_no_sai}</dd>
                        </dl>

                        <div className="db-question">
                          <HelpCircle size={13} />
                          <span>{item.can_luu_y}</span>
                        </div>

                        {onSelectSymbol ? (
                          <button
                            type="button"
                            className="db-open-chart"
                            onClick={() => onSelectSymbol(item.ma)}
                          >
                            Xem biểu đồ {item.ma}
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>

            {content.nhac_nho_rui_ro ? (
              <div className="db-footer-note">{content.nhac_nho_rui_ro}</div>
            ) : null}

            <div className="db-disclaimer">
              Bản tin do AI ({brief.model}) viết lại từ số liệu thật. Đây là thông tin
              tham khảo để bạn tự tìm hiểu, <b>không phải khuyến nghị đầu tư</b>.
            </div>
          </>
        ) : null}
      </div>

      <style>{`
        .db-panel { container-type: inline-size; }
        .db-header-right { display: flex; align-items: center; gap: 8px; }
        .db-stamp { font-size: 10px; color: var(--text-muted); }
        .db-refresh {
          background: none;
          border: 1px solid var(--border-color);
          border-radius: 999px;
          color: var(--text-muted);
          cursor: pointer;
          padding: 4px 7px;
          display: inline-flex;
        }
        .db-content { gap: 12px; }
        .db-error { font-size: 11px; color: var(--color-sell); }
        .db-empty {
          text-align: center;
          font-size: 12px;
          color: var(--text-muted);
          padding: 16px 8px;
          line-height: 1.6;
        }
        .db-cmd {
          display: inline-block;
          margin-top: 6px;
          font-size: 11px;
          background: rgba(0, 0, 0, 0.35);
          border: 1px solid var(--border-color);
          border-radius: 5px;
          padding: 4px 8px;
          color: var(--color-accent);
        }
        .db-lead {
          margin: 0;
          font-size: 13px;
          line-height: 1.65;
          color: var(--text-primary);
        }
        .db-macro {
          background: rgba(0, 0, 0, 0.22);
          border: 1px solid var(--border-color);
          border-radius: 10px;
          padding: 10px;
        }
        .db-macro-head {
          display: flex;
          align-items: center;
          gap: 5px;
          font-size: 9px;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          color: var(--text-muted);
          margin-bottom: 8px;
        }
        .db-macro-grid {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 8px;
        }
        @container (min-width: 520px) {
          .db-macro-grid { grid-template-columns: repeat(4, 1fr); }
        }
        .db-macro-item { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
        .db-macro-label {
          font-size: 9px;
          color: var(--text-muted);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .db-macro-value {
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 13px;
          color: var(--text-primary);
        }
        .db-macro-change { font-size: 10px; color: var(--text-muted); }
        .db-macro-change i { font-style: normal; opacity: 0.6; }
        .db-up { color: var(--color-buy) !important; }
        .db-down { color: var(--color-sell) !important; }
        .db-macro-note {
          margin: 8px 0 0;
          font-size: 11px;
          line-height: 1.6;
          color: var(--text-muted);
        }
        .db-items { display: flex; flex-direction: column; gap: 6px; }
        .db-item {
          border: 1px solid var(--border-color);
          border-radius: 10px;
          background: rgba(0, 0, 0, 0.2);
          overflow: hidden;
        }
        .db-item.open { border-color: rgba(6, 182, 212, 0.35); }
        .db-item-head {
          width: 100%;
          display: flex;
          align-items: baseline;
          gap: 10px;
          padding: 10px 12px;
          background: none;
          border: none;
          color: inherit;
          cursor: pointer;
          text-align: left;
        }
        .db-sym {
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 13px;
          color: var(--color-accent);
          flex: 0 0 auto;
        }
        .db-item-teaser {
          font-size: 11px;
          line-height: 1.5;
          color: var(--text-muted);
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }
        .db-item.open .db-item-teaser { -webkit-line-clamp: unset; color: var(--text-primary); }
        .db-item-body { padding: 0 12px 12px; }
        .db-fields { margin: 0; }
        .db-fields dt {
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: 0.4px;
          color: var(--text-muted);
          margin-top: 10px;
          display: flex;
          align-items: center;
          gap: 4px;
        }
        .db-fields dt.db-warn { color: var(--color-sell); }
        .db-fields dd {
          margin: 3px 0 0;
          font-size: 12px;
          line-height: 1.65;
          color: var(--text-primary);
        }
        .db-question {
          display: flex;
          align-items: flex-start;
          gap: 7px;
          margin-top: 12px;
          padding: 9px 10px;
          border-radius: 8px;
          background: rgba(6, 182, 212, 0.08);
          border: 1px solid rgba(6, 182, 212, 0.25);
          font-size: 12px;
          line-height: 1.6;
          color: var(--text-primary);
        }
        .db-open-chart {
          margin-top: 10px;
          font-size: 11px;
          padding: 6px 12px;
          border-radius: 999px;
          border: 1px solid var(--border-color);
          background: transparent;
          color: var(--text-muted);
          cursor: pointer;
        }
        .db-open-chart:hover { border-color: var(--color-accent); color: var(--color-accent); }
        .db-footer-note {
          font-size: 11px;
          line-height: 1.6;
          color: var(--text-muted);
          padding: 8px 10px;
          border-left: 2px solid var(--border-color);
        }
        .db-disclaimer {
          font-size: 9px;
          line-height: 1.5;
          color: var(--text-muted);
          opacity: 0.75;
        }
      `}</style>
    </div>
  );
}
