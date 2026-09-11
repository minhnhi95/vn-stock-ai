import { useCallback, useEffect, useState } from 'react';
import { ListChecks, RefreshCw, ChevronDown, ChevronRight, ArrowRight } from 'lucide-react';

/**
 * Kết luận của cả rổ — chỉ ĐỌC từ DB.
 *
 * Job nền (jobs/verdict_scan.py) tự quét VN100, mã đang giữ và mã đang đặt cảnh báo
 * mỗi ngày giao dịch sau giờ đóng cửa, bằng đúng quy tắc của thẻ "Kết luận". Panel cố
 * ý không có nút "quét ngay": một lượt mất khoảng 20 phút vì hạn mức vnstock.
 */

const VERDICT_CLASS = { buy_consider: 'vs-buy', wait: 'vs-wait', avoid: 'vs-avoid' };

// Với "Chờ thêm" không có đúng/sai (không ngụ ý hướng giá) nên không hiện dòng này.
const EDGE_TEXT = {
  better: 'Quá khứ với mã này: tốt hơn chọn bừa',
  same: 'Quá khứ với mã này: ngang chọn bừa',
  worse: 'Quá khứ với mã này: kém hơn chọn bừa',
};

const fmtPrice = (v) => (v === null || v === undefined ? '' : `${Math.round(v).toLocaleString('vi-VN')} đ`);

const fmtDay = (iso) => {
  if (!iso) return '';
  const [y, m, d] = String(iso).split('-');
  return d && m ? `${d}/${m}/${y}` : iso;
};

function Row({ row, onSelect }) {
  return (
    <div className={`vs-row ${VERDICT_CLASS[row.verdict] || ''}`}>
      <button type="button" className="vs-sym" onClick={() => onSelect?.(row.symbol)} title="Xem từng tiêu chí">
        {row.symbol}
      </button>
      <div className="vs-main">
        <div className="vs-line">
          <span className="vs-label">{row.label}</span>
          {row.held ? <span className="vs-held">Đang giữ</span> : null}
          {row.price !== null && row.price !== undefined ? <span className="vs-price">{fmtPrice(row.price)}</span> : null}
        </div>
        <div className="vs-headline">{row.headline}</div>
        {row.verdict !== 'wait' ? (
          <div className={`vs-edge vs-edge-${row.edge || 'none'}`}>
            {EDGE_TEXT[row.edge] || 'Chưa đủ dữ liệu quá khứ để đo'}
          </div>
        ) : null}
        {row.data_gaps?.length ? <div className="vs-gap">{row.data_gaps.join(' ')}</div> : null}
      </div>
    </div>
  );
}

function Section({ title, rows, onSelect, defaultOpen }) {
  const [open, setOpen] = useState(defaultOpen);
  if (!rows.length) return null;
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <div className="vs-section">
      <button type="button" className="vs-section-title" onClick={() => setOpen((o) => !o)}>
        <Icon size={12} />
        {title} ({rows.length})
      </button>
      {open ? rows.map((row) => <Row key={row.symbol} row={row} onSelect={onSelect} />) : null}
    </div>
  );
}

export default function VerdictScan({ apiBase, onSelectSymbol }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    if (!apiBase) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/verdict/scan`);
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`);
      setData(json);
    } catch (err) {
      setError(err.message || 'Không tải được kết quả quét');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    load();
  }, [load]);

  const rows = Array.isArray(data?.results) ? data.results : [];
  const changes = Array.isArray(data?.changes) ? data.changes : [];
  const errors = Array.isArray(data?.errors) ? data.errors : [];
  const counts = data?.counts || {};
  const byVerdict = (v) => rows.filter((r) => r.verdict === v);

  return (
    <div className="glass-panel">
      <div className="panel-header">
        <div className="panel-title">
          <ListChecks size={16} className="text-accent" />
          <span>Kết luận cả rổ</span>
        </div>
        <div className="vs-header-right">
          {data?.available ? <span className="vs-stamp">Phiên {fmtDay(data.scan_date || data.date)}</span> : null}
          <button type="button" className="vs-refresh" onClick={load} disabled={loading} title="Tải lại">
            <RefreshCw size={12} className={loading ? 'spin' : ''} />
          </button>
        </div>
      </div>

      <div className="panel-content vs-content">
        {error ? <div className="vs-error">{error}</div> : null}
        {loading && !data ? <div className="vs-empty">Đang tải...</div> : null}
        {data && !data.available ? <div className="vs-empty">{data.reason}</div> : null}

        {data?.available ? (
          <>
            <div className="vs-counts">
              <span className="vs-chip vs-buy">{counts.buy_consider || 0} có thể cân nhắc mua</span>
              <span className="vs-chip vs-wait">{counts.wait || 0} chờ thêm</span>
              <span className="vs-chip vs-avoid">{counts.avoid || 0} không nên mua</span>
            </div>

            {changes.length ? (
              <div className="vs-section">
                <div className="vs-section-title static">
                  Đổi kết luận so với phiên {fmtDay(data.previous_date)} ({changes.length})
                </div>
                {changes.map((c) => (
                  <div key={c.symbol} className="vs-change">
                    <button type="button" className="vs-sym" onClick={() => onSelectSymbol?.(c.symbol)}>
                      {c.symbol}
                    </button>
                    <span className={VERDICT_CLASS[c.from]}>{c.from_label}</span>
                    <ArrowRight size={11} />
                    <span className={VERDICT_CLASS[c.to]}>{c.to_label}</span>
                    {c.held ? <span className="vs-held">Đang giữ</span> : null}
                  </div>
                ))}
              </div>
            ) : null}

            <Section title="Mã bạn đang giữ" rows={rows.filter((r) => r.held)} onSelect={onSelectSymbol} defaultOpen />
            <Section title="Có thể cân nhắc mua" rows={byVerdict('buy_consider')} onSelect={onSelectSymbol} defaultOpen />
            <Section title="Không nên mua" rows={byVerdict('avoid')} onSelect={onSelectSymbol} defaultOpen={false} />
            <Section title="Chờ thêm" rows={byVerdict('wait')} onSelect={onSelectSymbol} defaultOpen={false} />

            {errors.length ? (
              <p className="vs-note">
                Không quét được {errors.length} mã: {errors.map((e) => e.symbol).join(', ')}.
              </p>
            ) : null}
            <p className="vs-note">
              Tự quét lúc 15:30 các ngày thứ 2 đến thứ 6, dùng giá đóng cửa của phiên đó. Bấm vào mã
              để xem từng tiêu chí và tỷ lệ đúng trong quá khứ.
            </p>
            <p className="vs-note">{data.disclaimer}</p>
          </>
        ) : null}
      </div>

      <style>{`
        .vs-header-right { display: flex; align-items: center; gap: 8px; }
        .vs-stamp { font-size: 10px; color: var(--text-muted); }
        .vs-refresh {
          background: none;
          border: 1px solid var(--border-color);
          border-radius: 999px;
          color: var(--text-muted);
          cursor: pointer;
          padding: 4px 7px;
          display: inline-flex;
        }
        .vs-content { gap: 10px; }
        .vs-error { font-size: 11px; color: var(--color-sell); }
        .vs-empty { font-size: 12px; color: var(--text-muted); line-height: 1.6; padding: 6px 2px; }
        .vs-counts { display: flex; flex-wrap: wrap; gap: 6px; }
        .vs-chip {
          font-size: 10.5px;
          padding: 3px 9px;
          border-radius: 999px;
          border: 1px solid var(--border-color);
        }
        .vs-chip.vs-buy { color: var(--color-buy); border-color: rgba(16, 185, 129, 0.45); }
        .vs-chip.vs-wait { color: var(--color-hold, #f59e0b); border-color: rgba(245, 158, 11, 0.4); }
        .vs-chip.vs-avoid { color: var(--color-sell); border-color: rgba(244, 63, 94, 0.45); }
        .vs-section { display: flex; flex-direction: column; gap: 5px; }
        .vs-section-title {
          display: flex;
          align-items: center;
          gap: 5px;
          background: none;
          border: none;
          padding: 0;
          cursor: pointer;
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          color: var(--text-muted);
          text-align: left;
        }
        .vs-section-title.static { cursor: default; }
        .vs-row {
          display: grid;
          grid-template-columns: 52px 1fr;
          gap: 8px;
          padding: 8px 10px;
          border: 1px solid var(--border-color);
          border-left-width: 3px;
          border-radius: 7px;
          background: rgba(0, 0, 0, 0.2);
        }
        .vs-row.vs-buy { border-left-color: var(--color-buy); }
        .vs-row.vs-wait { border-left-color: var(--color-hold, #f59e0b); }
        .vs-row.vs-avoid { border-left-color: var(--color-sell); }
        .vs-sym {
          background: none;
          border: none;
          padding: 0;
          cursor: pointer;
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 13px;
          color: var(--text-primary);
          text-align: left;
          align-self: start;
        }
        .vs-sym:hover { color: var(--accent-primary, #38bdf8); text-decoration: underline; }
        .vs-main { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
        .vs-line { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 11.5px; }
        .vs-label { font-weight: 600; }
        .vs-buy .vs-label, span.vs-buy { color: var(--color-buy); }
        .vs-wait .vs-label, span.vs-wait { color: var(--color-hold, #f59e0b); }
        .vs-avoid .vs-label, span.vs-avoid { color: var(--color-sell); }
        .vs-price {
          margin-left: auto;
          font-variant-numeric: tabular-nums;
          color: var(--text-muted);
          font-size: 11px;
        }
        .vs-held {
          font-size: 9.5px;
          padding: 1px 6px;
          border-radius: 999px;
          background: rgba(56, 189, 248, 0.15);
          color: var(--accent-primary, #38bdf8);
        }
        .vs-headline { font-size: 11px; line-height: 1.5; color: var(--text-secondary); }
        .vs-edge { font-size: 10px; color: var(--text-muted); }
        .vs-edge-better { color: var(--color-buy); }
        .vs-edge-worse { color: var(--color-sell); }
        .vs-gap { font-size: 10px; color: var(--color-hold, #f59e0b); }
        .vs-change {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          gap: 6px;
          font-size: 11px;
          padding: 6px 10px;
          border: 1px dashed var(--border-color);
          border-radius: 7px;
          color: var(--text-muted);
        }
        .vs-note { margin: 0; font-size: 10px; line-height: 1.5; color: var(--text-muted); }
      `}</style>
    </div>
  );
}
