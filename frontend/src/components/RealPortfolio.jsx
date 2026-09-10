import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Wallet,
  Upload,
  RefreshCw,
  AlertTriangle,
  Plus,
  Trash2,
  Info,
} from 'lucide-react';

/**
 * Danh mục THẬT — dựng từ sổ lệnh đã khớp ở công ty chứng khoán.
 *
 * Không có nút đặt lệnh và sẽ không bao giờ có: app chỉ ghi nhận, không kết nối
 * để mua bán hộ. Người dùng vẫn đặt lệnh ở app của công ty chứng khoán.
 */

const fmtVnd = (v, digits = 0) => {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  return `${Number(v).toLocaleString('en-US', { maximumFractionDigits: digits })} đ`;
};

const fmtShort = (v) => {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  const sign = n < 0 ? '-' : '';
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(2)} tỷ`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(1)} tr`;
  return `${sign}${abs.toLocaleString()} đ`;
};

const fmtSigned = (v) => {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  return `${n > 0 ? '+' : ''}${fmtShort(n)}`;
};

const fmtPct = (v) => {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`;
};

const tone = (v) => {
  if (v === null || v === undefined || Number(v) === 0) return '';
  return Number(v) > 0 ? 'rp-up' : 'rp-down';
};

const todayIso = () => new Date().toISOString().slice(0, 10);

export default function RealPortfolio({ apiBase }) {
  const [data, setData] = useState(null);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [importResult, setImportResult] = useState(null);
  const [importing, setImporting] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [showTxns, setShowTxns] = useState(false);
  const [transactions, setTransactions] = useState([]);
  const [form, setForm] = useState({
    date: todayIso(),
    symbol: '',
    side: 'BUY',
    quantity: '',
    price: '',
  });
  const [formError, setFormError] = useState(null);
  const fileRef = useRef(null);

  const load = useCallback(async () => {
    if (!apiBase) return;
    setLoading(true);
    setError(null);
    try {
      const [pRes, sRes] = await Promise.all([
        fetch(`${apiBase}/real/portfolio`),
        fetch(`${apiBase}/real/stats`),
      ]);
      const pJson = await pRes.json();
      if (!pRes.ok) throw new Error(pJson.detail || `HTTP ${pRes.status}`);
      setData(pJson);
      setStats(sRes.ok ? await sRes.json() : null);
    } catch (err) {
      setError(err.message || 'Không tải được danh mục thật');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    load();
  }, [load]);

  const loadTransactions = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/real/transactions`);
      const json = await res.json();
      setTransactions(Array.isArray(json.transactions) ? json.transactions : []);
    } catch {
      setTransactions([]);
    }
  }, [apiBase]);

  const handleFile = async (file) => {
    if (!file) return;
    setImporting(true);
    setImportResult(null);
    setError(null);
    try {
      const body = new FormData();
      body.append('file', file);
      const res = await fetch(`${apiBase}/real/import`, { method: 'POST', body });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`);
      setImportResult(json);
      await load();
      if (showTxns) await loadTransactions();
    } catch (err) {
      setImportResult({ error: err.message || 'Nhập file thất bại' });
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const submitManual = async (event) => {
    event.preventDefault();
    setFormError(null);
    try {
      const res = await fetch(`${apiBase}/real/transactions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          date: form.date,
          symbol: form.symbol,
          side: form.side,
          quantity: Number(form.quantity),
          price: Number(form.price),
        }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`);
      setForm({ ...form, symbol: '', quantity: '', price: '' });
      await load();
      if (showTxns) await loadTransactions();
    } catch (err) {
      setFormError(err.message || 'Không thêm được giao dịch');
    }
  };

  const removeTxn = async (id) => {
    if (!window.confirm('Xoá giao dịch này khỏi sổ?')) return;
    await fetch(`${apiBase}/real/transactions/${id}`, { method: 'DELETE' });
    await Promise.all([load(), loadTransactions()]);
  };

  const toggleTxns = async () => {
    const next = !showTxns;
    setShowTxns(next);
    if (next) await loadTransactions();
  };

  const summary = data?.summary || {};
  const positions = useMemo(() => data?.positions || [], [data]);
  const isEmpty = data?.empty;

  return (
    <div className="glass-panel rp-panel">
      <div className="panel-header">
        <div className="panel-title">
          <Wallet size={16} className="text-accent" />
          <span>Danh mục thật</span>
        </div>
        <div className="rp-header-actions">
          <button type="button" className="rp-mini-btn" onClick={toggleTxns}>
            {showTxns ? 'Ẩn sổ lệnh' : `Sổ lệnh${summary.txn_count ? ` (${summary.txn_count})` : ''}`}
          </button>
          <button type="button" className="rp-mini-btn" onClick={load} disabled={loading}>
            <RefreshCw size={11} className={loading ? 'spin' : ''} />
          </button>
        </div>
      </div>

      <div className="panel-content rp-content">
        <div className="rp-notice">
          <Info size={12} />
          <span>
            App chỉ <b>ghi nhận</b> lệnh đã khớp, không kết nối để mua bán hộ. Bạn vẫn
            đặt lệnh ở app công ty chứng khoán.
          </span>
        </div>

        {/* Nhập sao kê */}
        <div className="rp-import">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => handleFile(e.target.files?.[0])}
            hidden
          />
          <button
            type="button"
            className="btn btn-outline rp-import-btn"
            onClick={() => fileRef.current?.click()}
            disabled={importing}
          >
            <Upload size={13} />
            <span>{importing ? 'Đang đọc file...' : 'Nhập sao kê CSV'}</span>
          </button>
          <button type="button" className="rp-mini-btn" onClick={() => setShowForm((v) => !v)}>
            <Plus size={11} />
            <span>Nhập tay</span>
          </button>
        </div>

        {importResult ? (
          <div className={`rp-import-result ${importResult.error ? 'err' : 'ok'}`}>
            {importResult.error ? (
              <span>{importResult.error}</span>
            ) : (
              <>
                <span>
                  Đọc {importResult.parsed} dòng · thêm mới <b>{importResult.inserted}</b>
                  {importResult.duplicates ? ` · bỏ qua ${importResult.duplicates} dòng trùng` : ''}
                  {importResult.skipped_count ? ` · lỗi ${importResult.skipped_count} dòng` : ''}
                </span>
                {!importResult.fee_from_file && importResult.inserted ? (
                  <span className="rp-import-hint">
                    File không có cột phí — đã ước tính {(importResult.fee_rate_used * 100).toFixed(2)}%/lệnh
                    và thuế bán 0,1%.
                  </span>
                ) : null}
                {importResult.skipped_rows?.length ? (
                  <details className="rp-skipped">
                    <summary>Xem {importResult.skipped_count} dòng bị bỏ</summary>
                    {importResult.skipped_rows.map((r) => (
                      <div key={r.line} className="rp-skipped-row">
                        Dòng {r.line}: {r.reason}
                      </div>
                    ))}
                  </details>
                ) : null}
              </>
            )}
            <button type="button" className="rp-dismiss" onClick={() => setImportResult(null)}>
              ×
            </button>
          </div>
        ) : null}

        {showForm ? (
          <form className="rp-form" onSubmit={submitManual}>
            <input
              type="date"
              value={form.date}
              onChange={(e) => setForm({ ...form, date: e.target.value })}
              required
            />
            <input
              type="text"
              placeholder="Mã"
              maxLength={3}
              value={form.symbol}
              onChange={(e) => setForm({ ...form, symbol: e.target.value.toUpperCase() })}
              required
            />
            <select value={form.side} onChange={(e) => setForm({ ...form, side: e.target.value })}>
              <option value="BUY">Mua</option>
              <option value="SELL">Bán</option>
            </select>
            <input
              type="number"
              placeholder="KL"
              min="1"
              value={form.quantity}
              onChange={(e) => setForm({ ...form, quantity: e.target.value })}
              required
            />
            <input
              type="number"
              placeholder="Giá"
              min="1"
              value={form.price}
              onChange={(e) => setForm({ ...form, price: e.target.value })}
              required
            />
            <button type="submit" className="btn btn-outline rp-form-submit">
              Thêm
            </button>
            {formError ? <div className="rp-form-err">{formError}</div> : null}
          </form>
        ) : null}

        {error ? <div className="rp-error">{error}</div> : null}

        {isEmpty ? (
          <div className="rp-empty">
            {data?.reason || 'Chưa có giao dịch nào.'}
            <div className="rp-empty-hint">
              Tải file sao kê giao dịch từ app/web công ty chứng khoán (xuất CSV), hoặc
              nhập tay từng lệnh.
            </div>
          </div>
        ) : data ? (
          <>
            <div className="rp-summary">
              <div className="rp-cell">
                <span className="rp-cell-label">Giá trị thị trường</span>
                <span className="rp-cell-value">{fmtShort(summary.market_value)}</span>
                <span className="rp-cell-sub">vốn {fmtShort(summary.total_cost)}</span>
              </div>
              <div className="rp-cell">
                <span className="rp-cell-label">Lãi/lỗ chưa chốt</span>
                <span className={`rp-cell-value ${tone(summary.unrealized_pnl)}`}>
                  {fmtSigned(summary.unrealized_pnl)}
                </span>
                <span className={`rp-cell-sub ${tone(summary.unrealized_pct)}`}>
                  {fmtPct(summary.unrealized_pct)}
                </span>
              </div>
              <div className="rp-cell">
                <span className="rp-cell-label">Đã chốt lời/lỗ</span>
                <span className={`rp-cell-value ${tone(summary.realized_pnl)}`}>
                  {fmtSigned(summary.realized_pnl)}
                </span>
                <span className="rp-cell-sub">{summary.txn_count} lệnh</span>
              </div>
              <div className="rp-cell">
                <span className="rp-cell-label">Phí + thuế đã trả</span>
                <span className="rp-cell-value rp-down">{fmtShort(summary.cost_drag)}</span>
                {stats && !stats.empty && stats.cost_vs_gross_profit_pct !== null ? (
                  <span className="rp-cell-sub">
                    ăn {stats.cost_vs_gross_profit_pct}% lãi gộp
                  </span>
                ) : null}
              </div>
            </div>

            {data.warnings?.length ? (
              <div className="rp-warnings">
                {data.warnings.map((w, i) => (
                  <div key={i} className="rp-warning">
                    <AlertTriangle size={12} />
                    <span>{w}</span>
                  </div>
                ))}
              </div>
            ) : null}

            <div className="rp-table-wrap">
              <table className="rp-table">
                <thead>
                  <tr>
                    <th>Mã</th>
                    <th className="ta-right">KL</th>
                    <th className="ta-right">Giá vốn</th>
                    <th className="ta-right">Giá TT</th>
                    <th className="ta-right">Lãi/lỗ</th>
                    <th className="ta-right">%</th>
                    <th className="ta-right">Tỷ trọng</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => (
                    <tr key={p.symbol}>
                      <td className="rp-sym">{p.symbol}</td>
                      <td className="ta-right">{p.shares.toLocaleString()}</td>
                      <td className="ta-right">{fmtVnd(p.avg_cost)}</td>
                      <td className="ta-right">
                        {p.price_available ? fmtVnd(p.price) : <span className="rp-muted">chưa có giá</span>}
                      </td>
                      <td className={`ta-right ${tone(p.unrealized_pnl)}`}>
                        {fmtSigned(p.unrealized_pnl)}
                      </td>
                      <td className={`ta-right ${tone(p.unrealized_pct)}`}>{fmtPct(p.unrealized_pct)}</td>
                      <td className="ta-right rp-muted">
                        {p.weight_pct !== null && p.weight_pct !== undefined ? `${p.weight_pct}%` : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="rp-foot-note">
                Lãi/lỗ đã trừ phí mua trong giá vốn và trừ trước phí bán + thuế 0,1% nếu bán
                ngay hôm nay — tức là số tiền thật về tài khoản, không phải chênh lệch giá.
              </div>
            </div>

            {data.realized_by_symbol?.length ? (
              <details className="rp-realized">
                <summary>Lãi/lỗ đã chốt theo mã ({data.realized_by_symbol.length})</summary>
                <div className="rp-realized-list">
                  {data.realized_by_symbol.map((r) => (
                    <div key={r.symbol} className="rp-realized-row">
                      <span className="rp-sym">{r.symbol}</span>
                      <span className="rp-muted">{r.sold_qty.toLocaleString()} CP</span>
                      <span className={tone(r.pnl)}>{fmtSigned(r.pnl)}</span>
                      <span className={tone(r.pnl_pct)}>{fmtPct(r.pnl_pct)}</span>
                    </div>
                  ))}
                </div>
              </details>
            ) : null}
          </>
        ) : null}

        {showTxns ? (
          <div className="rp-txns">
            <div className="rp-txns-head">Sổ lệnh ({transactions.length})</div>
            {transactions.length === 0 ? (
              <div className="rp-muted">Chưa có giao dịch.</div>
            ) : (
              <div className="rp-txns-list">
                {transactions
                  .slice()
                  .reverse()
                  .map((t) => (
                    <div key={t.id} className="rp-txn-row">
                      <span className="rp-muted">{t.date}</span>
                      <span className="rp-sym">{t.symbol}</span>
                      <span className={t.side === 'BUY' ? 'rp-up' : 'rp-down'}>
                        {t.side === 'BUY' ? 'MUA' : 'BÁN'}
                      </span>
                      <span className="ta-right">{t.quantity.toLocaleString()}</span>
                      <span className="ta-right">{fmtVnd(t.price)}</span>
                      <span className="ta-right rp-muted">
                        phí {fmtVnd(t.fee)}
                        {t.tax ? ` · thuế ${fmtVnd(t.tax)}` : ''}
                      </span>
                      <button
                        type="button"
                        className="rp-del"
                        onClick={() => removeTxn(t.id)}
                        title="Xoá giao dịch"
                      >
                        <Trash2 size={11} />
                      </button>
                    </div>
                  ))}
              </div>
            )}
          </div>
        ) : null}
      </div>

      <style>{`
        .rp-panel { container-type: inline-size; }
        .rp-header-actions { display: flex; gap: 6px; align-items: center; }
        .rp-mini-btn {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          font-size: 10px;
          padding: 4px 8px;
          border-radius: 999px;
          border: 1px solid var(--border-color);
          background: transparent;
          color: var(--text-muted);
          cursor: pointer;
        }
        .rp-mini-btn:hover { border-color: var(--color-accent); color: var(--color-accent); }
        .rp-content { gap: 12px; }
        .rp-notice {
          display: flex;
          align-items: flex-start;
          gap: 6px;
          font-size: 10px;
          line-height: 1.5;
          color: var(--text-muted);
          background: rgba(6, 182, 212, 0.07);
          border: 1px solid rgba(6, 182, 212, 0.25);
          border-radius: 8px;
          padding: 7px 9px;
        }
        .rp-notice b { color: var(--text-primary); }
        .rp-import { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
        .rp-import-btn {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 12px;
          padding: 8px 12px;
        }
        .rp-import-result {
          position: relative;
          font-size: 10px;
          line-height: 1.5;
          padding: 8px 24px 8px 9px;
          border-radius: 8px;
          display: flex;
          flex-direction: column;
          gap: 3px;
        }
        .rp-import-result.ok {
          background: rgba(16, 185, 129, 0.09);
          border: 1px solid rgba(16, 185, 129, 0.28);
          color: var(--text-primary);
        }
        .rp-import-result.err {
          background: rgba(244, 63, 94, 0.09);
          border: 1px solid rgba(244, 63, 94, 0.28);
          color: var(--color-sell);
        }
        .rp-import-hint, .rp-skipped-row { color: var(--text-muted); }
        .rp-skipped summary { cursor: pointer; color: var(--text-muted); }
        .rp-dismiss {
          position: absolute;
          top: 4px;
          right: 6px;
          background: none;
          border: none;
          color: var(--text-muted);
          cursor: pointer;
          font-size: 14px;
          line-height: 1;
        }
        .rp-form {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 6px;
        }
        @container (min-width: 520px) {
          .rp-form { grid-template-columns: 1.3fr 0.7fr 0.8fr 0.8fr 1fr auto; align-items: center; }
        }
        .rp-form input, .rp-form select {
          background: rgba(0, 0, 0, 0.3);
          border: 1px solid var(--border-color);
          border-radius: 6px;
          padding: 7px 8px;
          color: var(--text-primary);
          font-size: 12px;
          min-width: 0;
        }
        .rp-form-submit { font-size: 12px; padding: 7px 14px; }
        .rp-form-err { grid-column: 1 / -1; font-size: 10px; color: var(--color-sell); }
        .rp-error {
          font-size: 11px;
          color: var(--color-sell);
          padding: 8px;
          border: 1px solid rgba(244, 63, 94, 0.3);
          border-radius: 8px;
        }
        .rp-empty {
          text-align: center;
          font-size: 12px;
          color: var(--text-muted);
          padding: 20px 10px;
        }
        .rp-empty-hint { font-size: 10px; margin-top: 6px; line-height: 1.5; }
        .rp-summary {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 8px;
        }
        @container (min-width: 520px) {
          .rp-summary { grid-template-columns: repeat(4, 1fr); }
        }
        .rp-cell {
          background: rgba(0, 0, 0, 0.25);
          border: 1px solid var(--border-color);
          border-radius: 8px;
          padding: 8px 10px;
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .rp-cell-label {
          font-size: 9px;
          text-transform: uppercase;
          letter-spacing: 0.4px;
          color: var(--text-muted);
        }
        .rp-cell-value {
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 15px;
          color: var(--text-primary);
        }
        .rp-cell-sub { font-size: 10px; color: var(--text-muted); }
        .rp-up { color: var(--color-buy) !important; }
        .rp-down { color: var(--color-sell) !important; }
        .rp-muted { color: var(--text-muted); }
        .rp-warnings { display: flex; flex-direction: column; gap: 5px; }
        .rp-warning {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 10px;
          line-height: 1.4;
          color: var(--color-sell);
          background: rgba(255, 176, 32, 0.1);
          border: 1px solid rgba(255, 176, 32, 0.3);
          border-radius: 6px;
          padding: 6px 8px;
        }
        .rp-table-wrap { overflow-x: auto; }
        .rp-table { width: 100%; border-collapse: collapse; font-size: 11px; }
        .rp-table th {
          text-align: left;
          font-size: 9px;
          text-transform: uppercase;
          letter-spacing: 0.4px;
          color: var(--text-muted);
          padding: 6px 8px;
          border-bottom: 1px solid var(--border-color);
          white-space: nowrap;
        }
        .rp-table td {
          padding: 7px 8px;
          border-bottom: 1px solid rgba(255, 255, 255, 0.04);
          white-space: nowrap;
          font-variant-numeric: tabular-nums;
        }
        .ta-right { text-align: right; }
        .rp-sym { font-family: var(--font-display); font-weight: 700; color: var(--text-primary); }
        .rp-foot-note {
          font-size: 9px;
          line-height: 1.5;
          color: var(--text-muted);
          padding: 8px 2px 0;
        }
        .rp-realized summary {
          cursor: pointer;
          font-size: 11px;
          color: var(--text-muted);
          padding: 4px 0;
        }
        .rp-realized-list { display: flex; flex-direction: column; gap: 4px; padding-top: 6px; }
        .rp-realized-row {
          display: grid;
          grid-template-columns: 50px 1fr auto auto;
          gap: 8px;
          align-items: center;
          font-size: 11px;
          padding: 5px 8px;
          background: rgba(0, 0, 0, 0.22);
          border-radius: 6px;
          font-variant-numeric: tabular-nums;
        }
        .rp-txns { border-top: 1px solid var(--border-color); padding-top: 10px; }
        .rp-txns-head {
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: 0.4px;
          color: var(--text-muted);
          margin-bottom: 6px;
        }
        .rp-txns-list { display: flex; flex-direction: column; gap: 3px; max-height: 240px; overflow-y: auto; }
        .rp-txn-row {
          display: grid;
          grid-template-columns: 74px 42px 38px 1fr 1fr 1.4fr 22px;
          gap: 6px;
          align-items: center;
          font-size: 10px;
          padding: 5px 6px;
          background: rgba(0, 0, 0, 0.22);
          border-radius: 5px;
          font-variant-numeric: tabular-nums;
        }
        .rp-del {
          background: none;
          border: none;
          color: var(--text-muted);
          cursor: pointer;
          padding: 2px;
        }
        .rp-del:hover { color: var(--color-sell); }
      `}</style>
    </div>
  );
}
