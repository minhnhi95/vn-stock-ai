import { useCallback, useEffect, useMemo, useState } from 'react';
import { Calculator, RefreshCw, AlertTriangle } from 'lucide-react';

/**
 * Kế hoạch vào lệnh: mua bao nhiêu cổ phiếu, cắt lỗ ở đâu, mất tối đa bao nhiêu tiền.
 *
 * Vì sao thẻ này quan trọng hơn thẻ "Kết luận": tỷ lệ đúng của quy tắc chọn mã, đo trên
 * chính dữ liệu từng mã, hầu hết chỉ ngang chọn bừa. Còn số tiền mất mỗi lệnh thì quyết
 * định được TRƯỚC khi mua. Phép tính ở backend (trade_plan.py), đây chỉ hiển thị.
 *
 * Vốn và mức rủi ro lưu trong localStorage của máy người dùng: đó là thông tin tài
 * chính cá nhân, không gửi đi đâu ngoài chính request tính toán này.
 */

const CAPITAL_KEY = 'trade_capital_vnd';
const RISK_KEY = 'trade_risk_pct';

const readNumber = (key, fallback) => {
  try {
    const raw = localStorage.getItem(key);
    const n = Number(raw);
    return raw !== null && Number.isFinite(n) && n > 0 ? n : fallback;
  } catch {
    return fallback;
  }
};

const fmt = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? '—' : Number(v).toLocaleString('vi-VN'));
const fmtVnd = (v) => (v === null || v === undefined ? '—' : `${fmt(Math.round(v))} đ`);

export default function TradePlan({ apiBase, symbol }) {
  const [capital, setCapital] = useState(() => readNumber(CAPITAL_KEY, 0));
  const [riskPct, setRiskPct] = useState(() => readNumber(RISK_KEY, 1));
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    try {
      if (capital > 0) localStorage.setItem(CAPITAL_KEY, String(capital));
      localStorage.setItem(RISK_KEY, String(riskPct));
    } catch {
      // Trình duyệt chặn lưu thì vẫn dùng được trong phiên này.
    }
  }, [capital, riskPct]);

  const load = useCallback(async () => {
    if (!apiBase || !symbol || !(capital > 0)) return;
    setLoading(true);
    setError(null);
    try {
      const url = `${apiBase}/trade-plan?symbol=${encodeURIComponent(symbol)}&capital=${capital}&risk_pct=${riskPct}`;
      const res = await fetch(url);
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`);
      setData(json);
    } catch (err) {
      setError(err.message || 'Không tính được kế hoạch');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [apiBase, symbol, capital, riskPct]);

  // Người dùng gõ số vốn thì chờ một nhịp rồi mới gọi, khỏi bắn request mỗi phím.
  useEffect(() => {
    const id = setTimeout(load, 400);
    return () => clearTimeout(id);
  }, [load]);

  const warnings = useMemo(() => data?.warnings || [], [data]);

  return (
    <div className="glass-panel">
      <div className="panel-header">
        <div className="panel-title">
          <Calculator size={16} className="text-accent" />
          <span>Kế hoạch vào lệnh: {symbol}</span>
        </div>
        <button type="button" className="tp-refresh" onClick={load} disabled={loading || !(capital > 0)} title="Tính lại">
          <RefreshCw size={12} className={loading ? 'spin' : ''} />
        </button>
      </div>

      <div className="panel-content tp-content">
        <div className="tp-inputs">
          <label className="tp-field">
            <span>Vốn dành cho cổ phiếu</span>
            <input
              type="number"
              inputMode="numeric"
              min="0"
              step="1000000"
              placeholder="VD: 100000000"
              value={capital || ''}
              onChange={(e) => setCapital(Number(e.target.value) || 0)}
            />
          </label>
          <label className="tp-field tp-field-small">
            <span>Chấp nhận mất mỗi lệnh</span>
            <select value={riskPct} onChange={(e) => setRiskPct(Number(e.target.value))}>
              {[0.5, 1, 1.5, 2, 3].map((v) => (
                <option key={v} value={v}>
                  {v}% vốn
                </option>
              ))}
            </select>
          </label>
        </div>

        {error ? <div className="tp-error">{error}</div> : null}
        {!(capital > 0) ? (
          <p className="tp-empty">
            Nhập số vốn bạn dành cho cổ phiếu để biết nên mua bao nhiêu. Số này chỉ lưu trên máy
            bạn.
          </p>
        ) : null}

        {data && !data.available ? <p className="tp-empty">{data.reason}</p> : null}

        {data?.available ? (
          <>
            <div className="tp-headline">
              <div className="tp-big">
                <span className="tp-big-value">{fmt(data.shares)}</span>
                <span className="tp-big-unit">cổ phiếu</span>
              </div>
              <div className="tp-sub">
                {fmtVnd(data.order_value)} — {data.capital_pct}% vốn
              </div>
            </div>

            <div className="tp-grid">
              <div className="tp-cell tp-loss">
                <span className="tp-cell-label">Cắt lỗ</span>
                <span className="tp-cell-value">{fmtVnd(data.stop?.price)}</span>
                <span className="tp-cell-note">
                  cách {data.stop?.distance_pct}% · {data.stop?.method}
                </span>
              </div>
              <div className="tp-cell tp-loss">
                <span className="tp-cell-label">Mất nếu chạm cắt lỗ</span>
                <span className="tp-cell-value">{fmtVnd(data.loss_if_stopped)}</span>
                <span className="tp-cell-note">{data.loss_pct_of_capital}% vốn, đã tính phí và thuế</span>
              </div>
              <div className="tp-cell tp-gain">
                <span className="tp-cell-label">Mục tiêu chốt lời</span>
                <span className="tp-cell-value">{fmtVnd(data.target?.price)}</span>
                <span className="tp-cell-note">lãi {fmtVnd(data.target?.gain)} nếu tới đích</span>
              </div>
              <div className="tp-cell">
                <span className="tp-cell-label">Phí mua</span>
                <span className="tp-cell-value">{fmtVnd(data.fees?.buy)}</span>
                <span className="tp-cell-note">
                  {data.fees?.fee_pct}% mua/bán, thuế bán {data.fees?.tax_pct}%
                </span>
              </div>
            </div>

            {warnings.map((w) => (
              <div key={w} className="tp-warn">
                <AlertTriangle size={12} />
                <span>{w}</span>
              </div>
            ))}

            {data.verdict ? (
              <p className="tp-note">
                Kết luận của mã này ở lượt quét gần nhất: <b>{data.verdict.label}</b>.
              </p>
            ) : null}
            <p className="tp-note">{data.rule}</p>
            <p className="tp-note">{data.disclaimer}</p>
          </>
        ) : null}
      </div>

      <style>{`
        .tp-refresh {
          background: none;
          border: 1px solid var(--border-color);
          border-radius: 999px;
          color: var(--text-muted);
          cursor: pointer;
          padding: 4px 7px;
          display: inline-flex;
        }
        .tp-content { gap: 10px; }
        .tp-inputs { display: flex; flex-wrap: wrap; gap: 8px; }
        .tp-field { display: flex; flex-direction: column; gap: 4px; flex: 1 1 180px; min-width: 0; }
        .tp-field-small { flex: 0 1 150px; }
        .tp-field span { font-size: 10px; text-transform: uppercase; letter-spacing: 0.4px; color: var(--text-muted); }
        .tp-field input, .tp-field select {
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
        .tp-field select option { background: #0b1220; }
        .tp-error { font-size: 11px; color: var(--color-sell); }
        .tp-empty { margin: 0; font-size: 11.5px; line-height: 1.6; color: var(--text-muted); }
        .tp-headline {
          display: flex;
          flex-wrap: wrap;
          align-items: baseline;
          gap: 10px;
          padding: 10px 12px;
          border: 1px solid rgba(56, 189, 248, 0.35);
          border-radius: 9px;
          background: rgba(56, 189, 248, 0.08);
        }
        .tp-big { display: flex; align-items: baseline; gap: 6px; }
        .tp-big-value {
          font-family: var(--font-display);
          font-size: 26px;
          font-weight: 700;
          color: var(--accent-primary, #38bdf8);
          font-variant-numeric: tabular-nums;
        }
        .tp-big-unit { font-size: 12px; color: var(--text-secondary); }
        .tp-sub { margin-left: auto; font-size: 11.5px; color: var(--text-secondary); }
        .tp-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; }
        .tp-cell {
          display: flex;
          flex-direction: column;
          gap: 2px;
          padding: 8px 10px;
          border: 1px solid var(--border-color);
          border-radius: 7px;
          background: rgba(0, 0, 0, 0.2);
        }
        .tp-cell-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.4px; color: var(--text-muted); }
        .tp-cell-value {
          font-family: var(--font-display);
          font-weight: 600;
          font-size: 14px;
          font-variant-numeric: tabular-nums;
        }
        .tp-loss .tp-cell-value { color: var(--color-sell); }
        .tp-gain .tp-cell-value { color: var(--color-buy); }
        .tp-cell-note { font-size: 10px; line-height: 1.4; color: var(--text-muted); }
        .tp-warn {
          display: flex;
          align-items: flex-start;
          gap: 6px;
          font-size: 11px;
          line-height: 1.5;
          color: var(--color-hold, #f59e0b);
        }
        .tp-note { margin: 0; font-size: 10px; line-height: 1.5; color: var(--text-muted); }
      `}</style>
    </div>
  );
}
