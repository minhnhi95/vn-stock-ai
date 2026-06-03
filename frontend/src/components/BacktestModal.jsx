import React, { useEffect, useRef, useState } from 'react';
import { createChart, ColorType } from 'lightweight-charts';
import { X, Play, BarChart2 } from 'lucide-react';

const STRATEGIES = [
  { id: 'ema_cross', label: 'EMA20/50 Crossover', desc: 'Mua khi EMA20 cắt lên EMA50, bán khi cắt xuống. Đơn giản, hợp xu hướng dài.' },
  { id: 'rsi_macd', label: 'RSI + MACD', desc: 'Mua khi RSI < 35 và MACD histogram chuyển dương; bán khi RSI > 70 hoặc MACD đảo chiều âm.' },
  { id: 'ai_ensemble', label: 'AI Ensemble (đa chỉ báo)', desc: 'Mô phỏng logic AI: yêu cầu 3/4 tín hiệu đồng thuận (EMA trend, RSI 40-65, MACD dương, volume vượt MA20).' },
];

const PERIODS = [
  { id: '6mo', label: '6 tháng' },
  { id: '1y', label: '1 năm' },
];

const fmt = (v, prec = 2) => (v === null || v === undefined || Number.isNaN(v) ? 'N/A' : Number(v).toFixed(prec));

export default function BacktestModal({ open, onClose, defaultSymbol, apiBase }) {
  const [mode, setMode] = useState('single'); // 'single' | 'vn30'
  const [symbol, setSymbol] = useState(defaultSymbol || 'FPT');
  const [strategy, setStrategy] = useState('ema_cross');
  const [period, setPeriod] = useState('1y');
  const [isRunning, setIsRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [batchResult, setBatchResult] = useState(null);
  const [error, setError] = useState(null);
  const [sortBy, setSortBy] = useState('strategy_return');

  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (open) setSymbol(defaultSymbol || 'FPT');
  }, [open, defaultSymbol]);

  useEffect(() => {
    if (!result || !chartContainerRef.current) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(chartContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#94a3b8', fontSize: 11 },
      grid: { vertLines: { color: 'rgba(255,255,255,0.03)' }, horzLines: { color: 'rgba(255,255,255,0.03)' } },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)' },
      timeScale: { borderColor: 'rgba(255,255,255,0.08)', timeVisible: false },
      width: chartContainerRef.current.clientWidth,
      height: 280,
    });
    chartRef.current = chart;

    const stratSeries = chart.addLineSeries({ color: '#06b6d4', lineWidth: 2, title: 'Chiến lược' });
    const bhSeries = chart.addLineSeries({ color: '#94a3b8', lineWidth: 1.5, lineStyle: 2, title: 'Mua & giữ' });

    const toPoint = (pt) => ({ time: pt.date, value: pt.nav });
    stratSeries.setData(result.equity_curve.map(toPoint));
    bhSeries.setData(result.buy_hold_curve.map(toPoint));
    chart.timeScale().fitContent();

    const onResize = () => chartContainerRef.current && chart.applyOptions({ width: chartContainerRef.current.clientWidth });
    window.addEventListener('resize', onResize);
    return () => { window.removeEventListener('resize', onResize); chart.remove(); chartRef.current = null; };
  }, [result]);

  const runBacktest = async () => {
    setIsRunning(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${apiBase}/backtest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, strategy, period, initial_capital: 100000000 }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }
      setResult(await res.json());
    } catch (e) {
      setError(e.message || 'Lỗi khi chạy backtest');
    } finally {
      setIsRunning(false);
    }
  };

  const runBatchBacktest = async () => {
    setIsRunning(true);
    setError(null);
    setBatchResult(null);
    try {
      const res = await fetch(`${apiBase}/backtest/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strategy, period, initial_capital: 100000000 }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }
      setBatchResult(await res.json());
    } catch (e) {
      setError(e.message || 'Lỗi khi chạy batch backtest');
    } finally {
      setIsRunning(false);
    }
  };

  const sortedBatch = React.useMemo(() => {
    if (!batchResult?.results) return [];
    const copy = [...batchResult.results];
    copy.sort((a, b) => (b[sortBy] || 0) - (a[sortBy] || 0));
    return copy;
  }, [batchResult, sortBy]);

  if (!open) return null;

  const m = result?.metrics;
  const bh = result?.buy_hold;
  const alpha = result?.alpha_percent;

  return (
    <div className="bt-backdrop" onClick={onClose}>
      <div className="bt-modal glass-panel" onClick={(e) => e.stopPropagation()}>
        <div className="bt-header">
          <div className="panel-title">
            <BarChart2 size={18} className="logo-icon" />
            <span>Backtest Strategy</span>
          </div>
          <button className="bt-close" onClick={onClose}><X size={18} /></button>
        </div>

        <div className="bt-tabs">
          <button className={`bt-tab ${mode === 'single' ? 'active' : ''}`} onClick={() => setMode('single')}>Một mã</button>
          <button className={`bt-tab ${mode === 'vn30' ? 'active' : ''}`} onClick={() => setMode('vn30')}>Quét VN30</button>
        </div>

        <div className="bt-controls">
          {mode === 'single' ? (
            <div className="bt-field">
              <label>Mã</label>
              <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase().slice(0, 3))} maxLength={3} />
            </div>
          ) : (
            <div className="bt-field"><label>Phạm vi</label><div className="bt-vn30-note">30 mã VN30</div></div>
          )}
          <div className="bt-field">
            <label>Chiến lược</label>
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
              {STRATEGIES.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </div>
          <div className="bt-field">
            <label>Khoảng thời gian</label>
            <select value={period} onChange={(e) => setPeriod(e.target.value)}>
              {PERIODS.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </div>
          <button
            className="btn btn-primary"
            onClick={mode === 'single' ? runBacktest : runBatchBacktest}
            disabled={isRunning || (mode === 'single' && symbol.length !== 3)}
          >
            <Play size={12} /> {isRunning ? 'Đang chạy...' : (mode === 'single' ? 'Chạy backtest' : 'Quét VN30')}
          </button>
        </div>

        <p className="bt-strategy-desc">
          {STRATEGIES.find(s => s.id === strategy)?.desc}
          {mode === 'vn30' ? ' · Quét VN30 mất 30-90s (chạy song song 8 mã).' : null}
        </p>

        {error && <div className="bt-error">{error}</div>}

        {mode === 'vn30' && batchResult && (
          <div className="bt-batch-wrap">
            <div className="bt-batch-summary">
              <div className="bt-batch-stat">
                <span className="bt-batch-label">Tổng</span>
                <span className="bt-batch-value">{batchResult.summary.total}</span>
              </div>
              <div className="bt-batch-stat">
                <span className="bt-batch-label">Có lãi</span>
                <span className="bt-batch-value good">{batchResult.summary.winners_count}</span>
              </div>
              <div className="bt-batch-stat">
                <span className="bt-batch-label">Beat buy & hold</span>
                <span className="bt-batch-value good">{batchResult.summary.beat_buy_hold_count}</span>
              </div>
              <div className="bt-batch-stat">
                <span className="bt-batch-label">Lỗi tải dữ liệu</span>
                <span className="bt-batch-value bad">{batchResult.summary.failed}</span>
              </div>
            </div>
            <div className="bt-batch-sort">
              Sắp xếp theo:
              {[
                { id: 'strategy_return', label: 'Lợi nhuận' },
                { id: 'alpha', label: 'Alpha' },
                { id: 'sharpe', label: 'Sharpe' },
                { id: 'win_rate', label: 'Win rate' },
              ].map(s => (
                <button key={s.id} className={`bt-sort-btn ${sortBy === s.id ? 'active' : ''}`} onClick={() => setSortBy(s.id)}>
                  {s.label}
                </button>
              ))}
            </div>
            <div className="bt-batch-table">
              <div className="bt-batch-row bt-batch-head">
                <span>#</span><span>Mã</span><span>Lợi nhuận</span><span>Buy & Hold</span>
                <span>Alpha</span><span>Max DD</span><span>Win</span><span>Lệnh</span><span>Sharpe</span>
              </div>
              {sortedBatch.map((r, i) => (
                <div className="bt-batch-row" key={r.symbol}>
                  <span className="bt-rank">#{i + 1}</span>
                  <span className="bt-batch-symbol">{r.symbol}</span>
                  <span className={r.strategy_return >= 0 ? 'good' : 'bad'}>{fmt(r.strategy_return)}%</span>
                  <span className={r.buy_hold_return >= 0 ? 'good' : 'bad'}>{fmt(r.buy_hold_return)}%</span>
                  <span className={r.alpha >= 0 ? 'good' : 'bad'}>{r.alpha >= 0 ? '+' : ''}{fmt(r.alpha)}%</span>
                  <span className="bad">{fmt(r.max_drawdown)}%</span>
                  <span>{fmt(r.win_rate, 1)}%</span>
                  <span>{r.num_trades}</span>
                  <span>{fmt(r.sharpe)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {mode === 'single' && result && (
          <>
            <div className="bt-metrics">
              <div className="bt-metric">
                <span className="bt-metric-label">Lợi nhuận chiến lược</span>
                <span className={`bt-metric-value ${m.total_return_percent >= 0 ? 'good' : 'bad'}`}>
                  {fmt(m.total_return_percent)}%
                </span>
              </div>
              <div className="bt-metric">
                <span className="bt-metric-label">Mua & giữ</span>
                <span className={`bt-metric-value ${bh.total_return_percent >= 0 ? 'good' : 'bad'}`}>
                  {fmt(bh.total_return_percent)}%
                </span>
              </div>
              <div className="bt-metric">
                <span className="bt-metric-label">Alpha</span>
                <span className={`bt-metric-value ${alpha >= 0 ? 'good' : 'bad'}`}>
                  {alpha >= 0 ? '+' : ''}{fmt(alpha)}%
                </span>
              </div>
              <div className="bt-metric">
                <span className="bt-metric-label">Max drawdown</span>
                <span className="bt-metric-value bad">{fmt(m.max_drawdown_percent)}%</span>
              </div>
              <div className="bt-metric">
                <span className="bt-metric-label">Win rate</span>
                <span className="bt-metric-value">{fmt(m.win_rate_percent, 1)}%</span>
              </div>
              <div className="bt-metric">
                <span className="bt-metric-label">Số lệnh</span>
                <span className="bt-metric-value">{m.num_trades}</span>
              </div>
              <div className="bt-metric">
                <span className="bt-metric-label">Sharpe (ann.)</span>
                <span className="bt-metric-value">{fmt(m.sharpe)}</span>
              </div>
              <div className="bt-metric">
                <span className="bt-metric-label">NAV cuối</span>
                <span className="bt-metric-value">{Math.round(m.final_nav).toLocaleString()} đ</span>
              </div>
            </div>

            <div className="bt-chart-wrap">
              <div className="bt-chart-legend">
                <span><span className="leg-dot" style={{ background: '#06b6d4' }} /> Chiến lược</span>
                <span><span className="leg-dot" style={{ background: '#94a3b8' }} /> Mua & giữ</span>
              </div>
              <div ref={chartContainerRef} style={{ width: '100%', height: 280 }} />
            </div>

            <div className="bt-trades">
              <div className="bt-trades-title">Lệnh đã thực hiện ({result.trades.length})</div>
              <div className="bt-trades-list">
                {result.trades.slice(-15).reverse().map((t, i) => (
                  <div key={i} className={`bt-trade-row ${t.type.toLowerCase()}`}>
                    <span className="bt-trade-date">{t.date}</span>
                    <span className="bt-trade-type">{t.type === 'BUY' ? 'MUA' : 'BÁN'}</span>
                    <span className="bt-trade-shares">{t.shares} CP</span>
                    <span className="bt-trade-price">{Math.round(t.price).toLocaleString()} đ</span>
                    {t.pnl !== undefined ? (
                      <span className={`bt-trade-pnl ${t.pnl >= 0 ? 'good' : 'bad'}`}>
                        {t.pnl >= 0 ? '+' : ''}{Math.round(t.pnl).toLocaleString()} ({fmt(t.pnl_percent)}%)
                      </span>
                    ) : <span />}
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>

      <style>{`
        .bt-backdrop {
          position: fixed; inset: 0; z-index: 200;
          background: rgba(2, 6, 23, 0.7);
          backdrop-filter: blur(4px);
          display: flex; align-items: center; justify-content: center;
          animation: fade-in 0.2s ease-out;
        }
        @keyframes fade-in { from { opacity: 0; } to { opacity: 1; } }
        .bt-modal {
          width: min(900px, 94vw);
          max-height: 92vh;
          padding: 18px 22px;
          display: flex; flex-direction: column;
          overflow-y: auto;
        }
        .bt-header {
          display: flex; align-items: center; justify-content: space-between;
          margin-bottom: 14px;
        }
        .bt-close {
          background: transparent; border: none; color: var(--text-muted);
          cursor: pointer; padding: 4px; border-radius: 6px;
        }
        .bt-close:hover { color: var(--text-primary); background: rgba(255,255,255,0.05); }
        .bt-controls {
          display: grid; grid-template-columns: 80px 1fr 1fr auto;
          gap: 10px; align-items: end;
        }
        .bt-field { display: flex; flex-direction: column; gap: 4px; }
        .bt-field label {
          font-size: 10px; color: var(--text-muted); text-transform: uppercase;
        }
        .bt-field input, .bt-field select {
          background: rgba(0,0,0,0.3); border: 1px solid var(--border-color);
          border-radius: 6px; padding: 8px 10px; color: #fff;
          font-size: 12px; font-family: var(--font-main);
        }
        .bt-strategy-desc {
          font-size: 11px; color: var(--text-muted);
          margin: 10px 0 14px; line-height: 1.4;
        }
        .bt-error {
          background: rgba(244,63,94,0.12);
          border: 1px solid rgba(244,63,94,0.4);
          color: #ffd9e0;
          padding: 10px 14px; border-radius: 8px;
          font-size: 12px; margin-bottom: 12px;
        }
        .bt-metrics {
          display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px;
          margin-bottom: 16px;
        }
        .bt-metric {
          background: rgba(0,0,0,0.25); border: 1px solid var(--border-color);
          border-radius: 8px; padding: 10px;
          display: flex; flex-direction: column; gap: 4px;
        }
        .bt-metric-label {
          font-size: 10px; color: var(--text-muted); text-transform: uppercase;
        }
        .bt-metric-value {
          font-family: var(--font-display); font-weight: 700; font-size: 16px;
        }
        .bt-metric-value.good { color: var(--color-buy); }
        .bt-metric-value.bad { color: var(--color-sell); }
        .bt-chart-wrap { position: relative; margin-bottom: 14px; }
        .bt-chart-legend {
          display: flex; gap: 14px; font-size: 11px; color: var(--text-secondary);
          margin-bottom: 6px;
        }
        .leg-dot {
          display: inline-block; width: 10px; height: 10px; border-radius: 50%;
          margin-right: 4px; vertical-align: middle;
        }
        .bt-trades-title {
          font-size: 12px; color: var(--text-secondary); font-weight: 600;
          margin-bottom: 6px;
        }
        .bt-trades-list { display: flex; flex-direction: column; gap: 4px; }
        .bt-trade-row {
          display: grid; grid-template-columns: 100px 50px 70px 100px 1fr;
          gap: 8px; font-size: 11px; padding: 6px 10px;
          background: rgba(0,0,0,0.2); border-radius: 6px;
          align-items: center;
        }
        .bt-trade-row.buy { border-left: 2px solid var(--color-buy); }
        .bt-trade-row.sell { border-left: 2px solid var(--color-sell); }
        .bt-trade-date { color: var(--text-muted); }
        .bt-trade-type { font-weight: 700; }
        .bt-trade-row.buy .bt-trade-type { color: var(--color-buy); }
        .bt-trade-row.sell .bt-trade-type { color: var(--color-sell); }
        .bt-trade-pnl.good { color: var(--color-buy); }
        .bt-trade-pnl.bad { color: var(--color-sell); }

        /* Tabs */
        .bt-tabs {
          display: flex;
          gap: 6px;
          margin-bottom: 12px;
          border-bottom: 1px solid var(--border-color);
        }
        .bt-tab {
          background: transparent;
          border: none;
          color: var(--text-muted);
          padding: 8px 14px;
          font-size: 12px;
          font-family: var(--font-display);
          font-weight: 600;
          cursor: pointer;
          border-bottom: 2px solid transparent;
          transition: all 0.15s;
        }
        .bt-tab:hover { color: var(--text-primary); }
        .bt-tab.active {
          color: var(--color-accent);
          border-bottom-color: var(--color-accent);
        }
        .bt-vn30-note {
          padding: 8px 10px;
          background: rgba(6, 182, 212, 0.08);
          border: 1px solid rgba(6, 182, 212, 0.2);
          border-radius: 6px;
          font-size: 11px;
          color: var(--color-accent);
        }

        /* Batch */
        .bt-batch-wrap {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .bt-batch-summary {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 8px;
        }
        .bt-batch-stat {
          background: rgba(0, 0, 0, 0.25);
          border: 1px solid var(--border-color);
          border-radius: 6px;
          padding: 8px 10px;
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .bt-batch-label {
          font-size: 9px;
          color: var(--text-muted);
          text-transform: uppercase;
        }
        .bt-batch-value {
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 16px;
        }
        .bt-batch-value.good { color: var(--color-buy); }
        .bt-batch-value.bad { color: var(--color-sell); }
        .bt-batch-sort {
          display: flex;
          gap: 6px;
          align-items: center;
          font-size: 11px;
          color: var(--text-muted);
        }
        .bt-sort-btn {
          background: rgba(0, 0, 0, 0.25);
          border: 1px solid var(--border-color);
          color: var(--text-secondary);
          padding: 3px 8px;
          border-radius: 4px;
          font-size: 10px;
          cursor: pointer;
        }
        .bt-sort-btn.active {
          background: rgba(6, 182, 212, 0.15);
          color: var(--color-accent);
          border-color: rgba(6, 182, 212, 0.4);
        }
        .bt-batch-table {
          display: flex;
          flex-direction: column;
          gap: 2px;
          max-height: 360px;
          overflow-y: auto;
        }
        .bt-batch-row {
          display: grid;
          grid-template-columns: 30px 50px 1fr 1fr 1fr 1fr 60px 50px 60px;
          gap: 6px;
          padding: 6px 8px;
          font-size: 11px;
          font-family: var(--font-display);
          border-radius: 4px;
          align-items: center;
        }
        .bt-batch-row:not(.bt-batch-head):hover {
          background: rgba(255, 255, 255, 0.03);
        }
        .bt-batch-head {
          color: var(--text-muted);
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: 0.3px;
          border-bottom: 1px solid var(--border-color);
          margin-bottom: 4px;
        }
        .bt-batch-row .good { color: var(--color-buy); }
        .bt-batch-row .bad { color: var(--color-sell); }
        .bt-rank { color: var(--text-muted); }
        .bt-batch-symbol { font-weight: 700; color: #fff; }
      `}</style>
    </div>
  );
}
