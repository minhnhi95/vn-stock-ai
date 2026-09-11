import { useCallback, useEffect, useMemo, useState } from 'react';
import { X, Search, RefreshCw } from 'lucide-react';
import useModalDismiss from '../hooks/useModalDismiss';
import VerdictRow from './VerdictRow';
import { ROW_CSS, coverageText, fmtDay } from './verdictScanUtils';

/**
 * Tìm mã đáng mua toàn thị trường — lọc và sắp xếp lượt quét mới nhất.
 *
 * Chỉ ĐỌC kết quả job nền đã tính (GET /api/verdict/scan); không gọi vnstock nên mở ra
 * là lọc được ngay. Mặc định hiện mã "Có thể cân nhắc mua", mã mà quy tắc từng đúng
 * hơn chọn bừa lên đầu — kèm ngay tỷ lệ đó để người dùng tự cân nhắc nên tin tới đâu.
 */

const VERDICT_FILTERS = [
  { id: 'buy_consider', label: 'Có thể cân nhắc mua' },
  { id: 'wait', label: 'Chờ thêm' },
  { id: 'avoid', label: 'Không nên mua' },
  { id: 'all', label: 'Tất cả' },
];

const EDGE_RANK = { better: 0, same: 1, worse: 3 };
const margin = (r) =>
  r.hit_ratio !== null && r.hit_ratio !== undefined && r.baseline_hit_ratio !== null && r.baseline_hit_ratio !== undefined
    ? r.hit_ratio - r.baseline_hit_ratio
    : -1;
const bySymbol = (a, b) => a.symbol.localeCompare(b.symbol);

const SORTS = {
  trust: {
    label: 'Quy tắc từng đúng nhất',
    cmp: (a, b) => (EDGE_RANK[a.edge] ?? 2) - (EDGE_RANK[b.edge] ?? 2) || margin(b) - margin(a) || bySymbol(a, b),
  },
  value: { label: 'Giao dịch nhiều nhất', cmp: (a, b) => (b.value || 0) - (a.value || 0) || bySymbol(a, b) },
  symbol: { label: 'Mã A-Z', cmp: bySymbol },
};

export default function MarketFinder({ apiBase, open, onClose, onSelectSymbol }) {
  useModalDismiss(open, onClose);

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [verdict, setVerdict] = useState('buy_consider');
  const [onlyBetter, setOnlyBetter] = useState(false);
  const [industry, setIndustry] = useState('');
  const [exchange, setExchange] = useState('');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState('trust');

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
    if (open) load();
  }, [open, load]);

  const rows = useMemo(() => (Array.isArray(data?.results) ? data.results : []), [data]);
  const industries = useMemo(
    () => [...new Set(rows.map((r) => r.industry || r.sector).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'vi')),
    [rows],
  );
  const exchanges = useMemo(() => [...new Set(rows.map((r) => r.exchange).filter(Boolean))].sort(), [rows]);

  const shown = useMemo(() => {
    const q = query.trim().toUpperCase();
    return rows
      .filter(
        (r) =>
          (verdict === 'all' || r.verdict === verdict) &&
          (!onlyBetter || r.edge === 'better') &&
          (!industry || (r.industry || r.sector) === industry) &&
          (!exchange || r.exchange === exchange) &&
          (!q || r.symbol.includes(q)),
      )
      .sort(SORTS[sort].cmp);
  }, [rows, verdict, onlyBetter, industry, exchange, query, sort]);

  if (!open) return null;

  const counts = data?.counts || {};
  const pick = (symbol) => {
    onSelectSymbol?.(symbol);
    onClose();
  };

  return (
    <div className="mf-backdrop" onClick={onClose}>
      <div className="mf-modal glass-panel" onClick={(e) => e.stopPropagation()}>
        <div className="mf-header">
          <div className="panel-title">
            <Search size={18} className="logo-icon" />
            <span>Tìm mã đáng mua toàn thị trường</span>
          </div>
          <div className="mf-header-right">
            <button type="button" className="mf-icon-btn" onClick={load} disabled={loading} title="Tải lại">
              <RefreshCw size={14} className={loading ? 'spin' : ''} />
            </button>
            <button type="button" className="mf-icon-btn" onClick={onClose} aria-label="Đóng">
              <X size={18} />
            </button>
          </div>
        </div>

        {error ? <div className="mf-error">{error}</div> : null}
        {loading && !data ? <div className="mf-empty">Đang tải...</div> : null}
        {data && !data.available ? <div className="mf-empty">{data.reason}</div> : null}

        {data?.available ? (
          <>
            <p className="mf-intro">
              Kết quả lượt quét phiên <b>{fmtDay(data.scan_date || data.date)}</b>. Kết luận tính bằng quy tắc cố
              định; dòng "Quá khứ" cho biết quy tắc từng đúng tới đâu với chính mã đó, so với chọn bừa một phiên bất
              kỳ. Bấm vào mã để xem từng tiêu chí.
            </p>
            {coverageText(data.coverage) ? <p className="mf-note">{coverageText(data.coverage)}</p> : null}

            <div className="mf-chips">
              {VERDICT_FILTERS.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  className={`mf-chip mf-chip-${f.id} ${verdict === f.id ? 'active' : ''}`}
                  onClick={() => setVerdict(f.id)}
                >
                  {f.label}
                  {f.id !== 'all' ? ` (${counts[f.id] || 0})` : ` (${rows.length})`}
                </button>
              ))}
            </div>

            <div className="mf-filters">
              <input
                type="text"
                placeholder="Tìm mã, VD: FPT"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <select value={industry} onChange={(e) => setIndustry(e.target.value)} aria-label="Ngành">
                <option value="">Mọi ngành</option>
                {industries.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              {exchanges.length ? (
                <select value={exchange} onChange={(e) => setExchange(e.target.value)} aria-label="Sàn">
                  <option value="">Mọi sàn</option>
                  {exchanges.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              ) : null}
              <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sắp xếp">
                {Object.entries(SORTS).map(([id, s]) => (
                  <option key={id} value={id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>

            <label className="mf-check">
              <input type="checkbox" checked={onlyBetter} onChange={(e) => setOnlyBetter(e.target.checked)} />
              <span>Chỉ mã mà quy tắc từng đúng hơn chọn bừa</span>
            </label>

            <div className="mf-count">{shown.length} mã</div>
            <div className="mf-results">
              {shown.map((row) => (
                <VerdictRow key={row.symbol} row={row} onSelect={pick} showMeta />
              ))}
              {!shown.length ? <div className="mf-empty">Không có mã nào khớp bộ lọc.</div> : null}
            </div>

            <p className="mf-note">{data.rule}</p>
            <p className="mf-note">{data.disclaimer}</p>
          </>
        ) : null}
      </div>

      <style>{`
        .mf-backdrop {
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
        .mf-modal {
          width: min(760px, 100%);
          max-height: min(90vh, 900px);
          overflow-y: auto;
          padding: 18px;
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .mf-header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
        .mf-header-right { display: flex; align-items: center; gap: 4px; }
        .mf-icon-btn {
          background: none;
          border: none;
          color: var(--text-muted);
          cursor: pointer;
          padding: 4px;
          display: inline-flex;
        }
        .mf-intro { margin: 0; font-size: 11px; line-height: 1.6; color: var(--text-muted); }
        .mf-intro b { color: var(--text-primary); }
        .mf-note { margin: 0; font-size: 10px; line-height: 1.5; color: var(--text-muted); }
        .mf-error { font-size: 11px; color: var(--color-sell); }
        .mf-empty { font-size: 12px; color: var(--text-muted); text-align: center; padding: 10px; line-height: 1.6; }
        .mf-chips { display: flex; flex-wrap: wrap; gap: 6px; }
        .mf-chip {
          font-size: 11px;
          padding: 5px 11px;
          border-radius: 999px;
          border: 1px solid var(--border-color);
          background: rgba(0, 0, 0, 0.25);
          color: var(--text-muted);
          cursor: pointer;
        }
        .mf-chip.active { color: var(--text-primary); border-color: var(--accent-primary, #38bdf8); }
        .mf-chip-buy_consider.active { color: var(--color-buy); border-color: var(--color-buy); }
        .mf-chip-wait.active { color: var(--color-hold, #f59e0b); border-color: var(--color-hold, #f59e0b); }
        .mf-chip-avoid.active { color: var(--color-sell); border-color: var(--color-sell); }
        .mf-filters { display: flex; flex-wrap: wrap; gap: 8px; }
        .mf-filters input,
        .mf-filters select {
          flex: 1 1 140px;
          min-width: 0;
          background: rgba(0, 0, 0, 0.3);
          border: 1px solid var(--border-color);
          border-radius: 7px;
          padding: 8px 10px;
          color: var(--text-primary);
          font-size: 12px;
        }
        .mf-filters select option { background: #0b1220; }
        .mf-check { display: flex; align-items: center; gap: 7px; font-size: 11.5px; color: var(--text-secondary); cursor: pointer; }
        .mf-count { font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); }
        .mf-results { display: flex; flex-direction: column; gap: 6px; }
        ${ROW_CSS}
      `}</style>
    </div>
  );
}
