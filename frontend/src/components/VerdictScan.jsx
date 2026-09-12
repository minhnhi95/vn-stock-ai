import { useCallback, useEffect, useState } from 'react';
import { ListChecks, RefreshCw, ChevronDown, ChevronRight, ArrowRight, Search } from 'lucide-react';
import VerdictRow from './VerdictRow';
import { ROW_CSS, VERDICT_CLASS, coverageText, fmtDay, scopeLabel } from './verdictScanUtils';

/**
 * Tóm tắt lượt quét gần nhất — chỉ ĐỌC từ DB.
 *
 * Job nền (jobs/verdict_scan.py) lọc thanh khoản cả sàn rồi chấm kết luận từng mã mỗi
 * ngày giao dịch sau giờ đóng cửa, bằng đúng quy tắc của thẻ "Kết luận". Panel chỉ
 * hiện phần cần thấy ngay (mã đổi kết luận, mã đang giữ, mã có thể mua); danh sách đầy
 * đủ kèm bộ lọc nằm trong modal "Tìm mã". Không có nút "quét ngay": một lượt mất ~40
 * phút vì hạn mức vnstock.
 */

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
      {open ? rows.map((row) => <VerdictRow key={row.symbol} row={row} onSelect={onSelect} />) : null}
    </div>
  );
}

export default function VerdictScan({ apiBase, onSelectSymbol, onOpenFinder }) {
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
  const coverage = coverageText(data?.coverage);
  const scope = data?.available ? scopeLabel(data.coverage) : 'cổ phiếu';

  return (
    <div className="glass-panel">
      <div className="panel-header">
        <div className="panel-title">
          <ListChecks size={16} className="text-accent" />
          <span>Kết luận {scope}</span>
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
            {coverage ? <p className="vs-note">{coverage}</p> : null}

            {onOpenFinder ? (
              <button type="button" className="btn btn-outline vs-finder-btn" onClick={onOpenFinder}>
                <Search size={13} />
                <span>Tìm và lọc toàn bộ {rows.length} mã</span>
              </button>
            ) : null}

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
            <Section
              title="Có thể cân nhắc mua"
              rows={rows.filter((r) => r.verdict === 'buy_consider')}
              onSelect={onSelectSymbol}
              defaultOpen
            />

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
        .vs-finder-btn {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          font-size: 12px;
          padding: 8px 12px;
        }
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
        ${ROW_CSS}
      `}</style>
    </div>
  );
}
