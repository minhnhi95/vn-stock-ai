import { useCallback, useEffect, useState } from 'react';
import { PiggyBank, RefreshCw, Check, X, AlertTriangle, HelpCircle, Pencil } from 'lucide-react';

/**
 * Tài chính cá nhân: tổng tài sản, phân bổ, kiểm tra an toàn.
 *
 * Đầu tư an toàn bắt đầu từ việc biết tiền đang nằm ở đâu, trước cả chuyện chọn mã.
 * Phần cổ phiếu lấy từ danh mục thật; phần còn lại người dùng tự nhập. Phép tính và các
 * ngưỡng nằm ở backend (personal_finance_service.py), đây chỉ hiển thị.
 */

const STATUS = {
  pass: { Icon: Check, cls: 'pf-pass' },
  warn: { Icon: AlertTriangle, cls: 'pf-warn' },
  fail: { Icon: X, cls: 'pf-fail' },
  unknown: { Icon: HelpCircle, cls: 'pf-unknown' },
};

const COLORS = {
  cash: '#38bdf8',
  savings: '#10b981',
  broker_cash: '#a78bfa',
  stocks: '#f59e0b',
  other_assets: '#94a3b8',
};

const MONEY_FIELDS = ['cash', 'savings', 'broker_cash', 'other_assets', 'debts', 'monthly_expenses'];

const fmtVnd = (v) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? '—' : `${Math.round(Number(v)).toLocaleString('vi-VN')} đ`;

const fmtShort = (v) => {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  const abs = Math.abs(n);
  const sign = n < 0 ? '−' : '';
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toLocaleString('vi-VN', { maximumFractionDigits: 2 })} tỷ`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} triệu`;
  return `${sign}${abs.toLocaleString('vi-VN')} đ`;
};

export default function PersonalFinance({ apiBase }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({});

  const load = useCallback(async () => {
    if (!apiBase) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/finance`);
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`);
      setData(json);
      if (json.needs_setup) setEditing(true);
    } catch (err) {
      setError(err.message || 'Không tải được dữ liệu tài chính');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    load();
  }, [load]);

  const startEdit = () => {
    const inputs = data?.inputs || {};
    setForm(Object.fromEntries(Object.keys(data?.fields || {}).map((k) => [k, inputs[k] ?? ''])));
    setEditing(true);
  };

  useEffect(() => {
    if (editing && data && !Object.keys(form).length) {
      const inputs = data.inputs || {};
      setForm(Object.fromEntries(Object.keys(data.fields || {}).map((k) => [k, inputs[k] ?? ''])));
    }
  }, [editing, data, form]);

  const save = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v === '' ? null : v]));
      const res = await fetch(`${apiBase}/finance`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`);
      setData(json);
      setEditing(false);
    } catch (err) {
      setError(err.message || 'Không lưu được');
    } finally {
      setSaving(false);
    }
  };

  const allocation = data?.allocation || [];
  const checks = data?.checks || [];
  const stocks = data?.stocks || {};

  return (
    <div className="glass-panel">
      <div className="panel-header">
        <div className="panel-title">
          <PiggyBank size={16} className="text-accent" />
          <span>Tài chính cá nhân</span>
        </div>
        <div className="pf-header-right">
          {data && !editing ? (
            <button type="button" className="pf-icon-btn" onClick={startEdit} title="Sửa số liệu">
              <Pencil size={12} />
            </button>
          ) : null}
          <button type="button" className="pf-icon-btn" onClick={load} disabled={loading} title="Tải lại">
            <RefreshCw size={12} className={loading ? 'spin' : ''} />
          </button>
        </div>
      </div>

      <div className="panel-content pf-content">
        {error ? <div className="pf-error">{error}</div> : null}
        {loading && !data ? <div className="pf-empty">Đang tính...</div> : null}

        {data ? (
          <>
            <div className="pf-headline">{data.headline}</div>

            {editing ? (
              <form className="pf-form" onSubmit={save}>
                {Object.entries(data.fields || {}).map(([key, label]) => (
                  <label key={key} className="pf-field">
                    <span>{label}</span>
                    <input
                      type="text"
                      inputMode="decimal"
                      placeholder={key === 'savings_rate_pct' ? 'VD: 5,5' : MONEY_FIELDS.includes(key) ? 'VD: 50.000.000' : ''}
                      value={form[key] ?? ''}
                      onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                    />
                  </label>
                ))}
                <p className="pf-note">
                  Bỏ trống ô nào không có. Phần cổ phiếu app tự lấy từ danh mục thật. Số liệu chỉ lưu trong
                  database của app trên máy bạn.
                </p>
                <div className="pf-actions">
                  <button type="submit" className="btn btn-primary pf-save" disabled={saving}>
                    {saving ? 'Đang lưu...' : 'Lưu và kiểm tra'}
                  </button>
                  {!data.needs_setup ? (
                    <button type="button" className="btn btn-outline pf-cancel" onClick={() => setEditing(false)}>
                      Huỷ
                    </button>
                  ) : null}
                </div>
              </form>
            ) : null}

            {!data.needs_setup ? (
              <>
                <div className="pf-networth">
                  <div>
                    <span className="pf-label">Tài sản ròng</span>
                    <span className="pf-big">{fmtShort(data.net_worth)}</span>
                  </div>
                  <div className="pf-sub">
                    Tổng tài sản {fmtShort(data.total_assets)}
                    {data.debts ? ` − nợ ${fmtShort(data.debts)}` : ''}
                  </div>
                </div>

                {allocation.length ? (
                  <>
                    <div className="pf-bar" role="img" aria-label="Phân bổ tài sản">
                      {allocation.map((a) => (
                        <span
                          key={a.key}
                          style={{ width: `${a.pct}%`, background: COLORS[a.key] || '#64748b' }}
                          title={`${a.label}: ${a.pct}%`}
                        />
                      ))}
                    </div>
                    <div className="pf-legend">
                      {allocation.map((a) => (
                        <span key={a.key}>
                          <i style={{ background: COLORS[a.key] || '#64748b' }} />
                          {a.label} <b>{a.pct}%</b> · {fmtShort(a.value)}
                        </span>
                      ))}
                    </div>
                  </>
                ) : null}
              </>
            ) : null}

            {stocks.cost ? (
              <div className="pf-stocks">
                Cổ phiếu: giá trị {fmtVnd(stocks.value)} · giá vốn {fmtVnd(stocks.cost)}
                {stocks.unrealized_pnl !== null && stocks.unrealized_pnl !== undefined ? (
                  <b className={stocks.unrealized_pnl < 0 ? 'pf-neg' : 'pf-pos'}>
                    {' '}
                    · {stocks.unrealized_pnl < 0 ? 'lỗ' : 'lãi'} {fmtShort(Math.abs(stocks.unrealized_pnl))} (
                    {stocks.unrealized_pct}%)
                  </b>
                ) : null}
                {!stocks.priced ? <span className="pf-note"> — chưa lấy được giá, đang dùng giá vốn</span> : null}
              </div>
            ) : null}

            <div className="pf-checks">
              {checks.map((c) => {
                const meta = STATUS[c.status] || STATUS.unknown;
                const Icon = meta.Icon;
                return (
                  <div key={c.key} className={`pf-check ${meta.cls}`}>
                    <Icon size={13} className="pf-check-icon" />
                    <span className="pf-check-label">{c.label}</span>
                    <span className="pf-check-value">{c.display}</span>
                    <span className="pf-check-threshold">Ngưỡng: {c.threshold}</span>
                    {c.explain ? <span className="pf-check-explain">{c.explain}</span> : null}
                  </div>
                );
              })}
            </div>

            {data.savings_comparison ? <p className="pf-compare">{data.savings_comparison.text}</p> : null}
            <p className="pf-note">{data.disclaimer}</p>
          </>
        ) : null}
      </div>

      <style>{`
        .pf-header-right { display: flex; gap: 6px; }
        .pf-icon-btn {
          background: none;
          border: 1px solid var(--border-color);
          border-radius: 999px;
          color: var(--text-muted);
          cursor: pointer;
          padding: 4px 7px;
          display: inline-flex;
        }
        .pf-content { gap: 10px; }
        .pf-error { font-size: 11px; color: var(--color-sell); }
        .pf-empty { font-size: 12px; color: var(--text-muted); padding: 8px 0; }
        .pf-headline { font-size: 12px; line-height: 1.5; color: var(--text-primary); font-weight: 600; }
        .pf-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 8px; }
        .pf-field { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
        .pf-field span { font-size: 10px; color: var(--text-muted); }
        .pf-field input {
          background: rgba(0, 0, 0, 0.3);
          border: 1px solid var(--border-color);
          border-radius: 7px;
          padding: 8px 10px;
          color: var(--text-primary);
          font-family: var(--font-display);
          font-size: 13px;
          font-variant-numeric: tabular-nums;
          min-width: 0;
        }
        .pf-actions { grid-column: 1 / -1; display: flex; gap: 8px; }
        .pf-save, .pf-cancel { font-size: 12px; padding: 8px 14px; }
        .pf-networth { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 8px; }
        .pf-label { display: block; font-size: 10px; text-transform: uppercase; letter-spacing: 0.4px; color: var(--text-muted); }
        .pf-big { font-family: var(--font-display); font-size: 24px; font-weight: 700; font-variant-numeric: tabular-nums; }
        .pf-sub { font-size: 11px; color: var(--text-secondary); }
        .pf-bar { display: flex; height: 12px; border-radius: 999px; overflow: hidden; background: rgba(255, 255, 255, 0.05); }
        .pf-bar span { display: block; height: 100%; }
        .pf-legend { display: flex; flex-wrap: wrap; gap: 6px 12px; font-size: 10.5px; color: var(--text-secondary); }
        .pf-legend span { display: inline-flex; align-items: center; gap: 5px; }
        .pf-legend i { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
        .pf-stocks { font-size: 11px; color: var(--text-secondary); line-height: 1.5; }
        .pf-neg { color: var(--color-sell); }
        .pf-pos { color: var(--color-buy); }
        .pf-checks { display: flex; flex-direction: column; gap: 6px; }
        .pf-check {
          display: grid;
          grid-template-columns: 16px 1fr auto;
          column-gap: 8px;
          row-gap: 2px;
          align-items: center;
          padding: 8px 10px;
          border: 1px solid var(--border-color);
          border-left-width: 3px;
          border-radius: 7px;
          background: rgba(0, 0, 0, 0.2);
          font-size: 11.5px;
        }
        .pf-pass { border-left-color: var(--color-buy); }
        .pf-warn { border-left-color: var(--color-hold, #f59e0b); }
        .pf-fail { border-left-color: var(--color-sell); }
        .pf-unknown { border-left-color: var(--text-muted); }
        .pf-pass .pf-check-icon { color: var(--color-buy); }
        .pf-warn .pf-check-icon, .pf-warn .pf-check-value { color: var(--color-hold, #f59e0b); }
        .pf-fail .pf-check-icon, .pf-fail .pf-check-value { color: var(--color-sell); }
        .pf-unknown .pf-check-icon { color: var(--text-muted); }
        .pf-check-label { color: var(--text-primary); }
        .pf-check-value { font-family: var(--font-display); font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .pf-check-threshold { grid-column: 2 / -1; font-size: 10px; color: var(--text-muted); }
        .pf-check-explain { grid-column: 2 / -1; font-size: 10.5px; line-height: 1.5; color: var(--text-secondary); }
        .pf-compare { margin: 0; font-size: 11px; line-height: 1.6; color: var(--text-secondary); }
        .pf-note { margin: 0; font-size: 10px; line-height: 1.5; color: var(--text-muted); }
      `}</style>
    </div>
  );
}
