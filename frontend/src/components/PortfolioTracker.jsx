import React, { useState } from 'react';
import { Briefcase, DollarSign, History, Shield, ArrowUpRight, ArrowDownRight, Lock } from 'lucide-react';

const T_PLUS_LOCK_MS = 2 * 24 * 3600 * 1000;

const availableSharesOf = (holding, now = Date.now()) => {
  if (!holding?.lots) return holding?.shares || 0;
  return holding.lots.filter(l => (now - l.buyAt) >= T_PLUS_LOCK_MS).reduce((s, l) => s + l.shares, 0);
};

export default function PortfolioTracker({ portfolio, transactionHistory, onSellHolding }) {
  const [activeTab, setActiveTab] = useState('holdings');
  const now = Date.now();

  // Defensive defaults — server có thể chưa load hoặc trả null.
  const holdings = Array.isArray(portfolio?.holdings) ? portfolio.holdings : [];
  const cash = Number.isFinite(portfolio?.cash) ? portfolio.cash : 0;
  const txns = Array.isArray(transactionHistory) ? transactionHistory : [];

  const totalHoldingValue = holdings.reduce(
    (sum, h) => sum + (Number(h?.shares) || 0) * (Number(h?.currentPrice) || 0),
    0,
  );
  const netAssetValue = cash + totalHoldingValue;
  const initialCapital = 100000000;
  const totalProfitLoss = netAssetValue - initialCapital;
  const totalProfitLossPercent = (totalProfitLoss / initialCapital) * 100;

  return (
    <div className="glass-panel portfolio-container">
      <div className="panel-header">
        <div className="panel-title">
          <Briefcase className="logo-icon" size={18} />
          <span>Danh mục giả lập (Paper Portfolio)</span>
        </div>
        <div className="portfolio-tabs">
          <button 
            className={`tab-btn ${activeTab === 'holdings' ? 'active' : ''}`}
            onClick={() => setActiveTab('holdings')}
          >
            Đang nắm giữ
          </button>
          <button 
            className={`tab-btn ${activeTab === 'history' ? 'active' : ''}`}
            onClick={() => setActiveTab('history')}
          >
            Nhật ký lệnh ({txns.length})
          </button>
        </div>
      </div>

      <div className="panel-content portfolio-content">
        {/* Portfolio Stats Summary */}
        <div className="portfolio-summary-card">
          <div className="summary-col">
            <span className="summary-label">Tài sản ròng (NAV)</span>
            <span className="summary-val font-display">{netAssetValue.toLocaleString()} đ</span>
          </div>
          <div className="summary-col">
            <span className="summary-label">Tiền mặt khả dụng</span>
            <span className="summary-val font-display" style={{ color: '#06b6d4' }}>{cash.toLocaleString()} đ</span>
          </div>
          <div className="summary-col">
            <span className="summary-label">Tổng Lời/Lỗ</span>
            <span className={`summary-val font-display ${totalProfitLoss >= 0 ? 'text-buy' : 'text-sell'}`}>
              {totalProfitLoss >= 0 ? '+' : ''}{totalProfitLoss.toLocaleString()} đ 
              <span className="pl-percent">({totalProfitLossPercent.toFixed(2)}%)</span>
            </span>
          </div>
        </div>

        {/* Tab Content */}
        {activeTab === 'holdings' ? (
          <div className="holdings-list-wrapper">
            {holdings.length === 0 ? (
              <div className="empty-portfolio">
                Chưa có cổ phiếu nào. Sử dụng bảng điều khiển biểu đồ bên trái để đặt lệnh Mua.
              </div>
            ) : (
              <table className="portfolio-table">
                <thead>
                  <tr>
                    <th>Mã</th>
                    <th className="txt-right">Số lượng</th>
                    <th className="txt-right">Giá vốn</th>
                    <th className="txt-right">Giá thị trường</th>
                    <th className="txt-right">Lời/Lỗ</th>
                    <th>Thao tác</th>
                  </tr>
                </thead>
                <tbody>
                  {holdings.map((h, i) => {
                    const costBasis = h.shares * h.avgPrice;
                    const marketValue = h.shares * h.currentPrice;
                    const pl = marketValue - costBasis;
                    const plPercent = (pl / costBasis) * 100;
                    const available = availableSharesOf(h, now);
                    const locked = h.shares - available;
                    const canSell = available > 0;

                    return (
                      <tr key={i}>
                        <td className="ticker-cell">{h.symbol}</td>
                        <td className="txt-right font-display">
                          {h.shares}
                          {locked > 0 ? (
                            <span className="lock-tag" title={`${locked} CP đang khóa T+`}>
                              <Lock size={9} /> {locked}
                            </span>
                          ) : null}
                        </td>
                        <td className="txt-right font-display">{h.avgPrice.toLocaleString()}</td>
                        <td className="txt-right font-display">{h.currentPrice.toLocaleString()}</td>
                        <td className={`txt-right font-display ${pl >= 0 ? 'text-buy' : 'text-sell'}`}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 2 }}>
                            {pl >= 0 ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
                            <span>{plPercent.toFixed(2)}%</span>
                          </div>
                          <span style={{ fontSize: '10px', opacity: 0.8 }}>{pl >= 0 ? '+' : ''}{pl.toLocaleString()}</span>
                        </td>
                        <td>
                          <button
                            className="btn btn-sell btn-xs"
                            onClick={() => onSellHolding(h.symbol)}
                            disabled={!canSell}
                            title={canSell ? `Bán ${available} CP khả dụng` : 'Cổ phiếu đang khóa T+'}
                            style={{ padding: '4px 8px', fontSize: '11px', borderRadius: '4px', opacity: canSell ? 1 : 0.4, cursor: canSell ? 'pointer' : 'not-allowed' }}
                          >
                            Bán {available > 0 && available < h.shares ? `(${available})` : 'hết'}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        ) : (
          <div className="transaction-history-wrapper">
            {txns.length === 0 ? (
              <div className="empty-portfolio">Chưa có lịch sử giao dịch.</div>
            ) : (
              <table className="portfolio-table">
                <thead>
                  <tr>
                    <th>Thời gian</th>
                    <th>Mã</th>
                    <th>Loại</th>
                    <th className="txt-right">Số lượng</th>
                    <th className="txt-right">Giá khớp</th>
                    <th className="txt-right">Tổng tiền</th>
                    <th>Bởi</th>
                  </tr>
                </thead>
                <tbody>
                  {txns.map((t, i) => (
                    <tr key={i}>
                      <td style={{ fontSize: '10px', color: '#64748b' }}>
                        {new Date(t.timestamp).toLocaleTimeString()}
                      </td>
                      <td className="ticker-cell">{t.symbol}</td>
                      <td>
                        <span className={`trade-type-badge ${t.type.toLowerCase()}`}>
                          {t.type === 'BUY' ? 'MUA' : 'BÁN'}
                        </span>
                      </td>
                      <td className="txt-right font-display">{t.shares}</td>
                      <td className="txt-right font-display">{t.price.toLocaleString()}</td>
                      <td className="txt-right font-display">{(t.shares * t.price).toLocaleString()}</td>
                      <td>
                        <span className={`executor-badge ${t.executor.toLowerCase()}`}>
                          {t.executor === 'AI' ? '🤖 Bot AI' : '👤 Tôi'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>

      <style>{`
        .portfolio-container {
          flex-shrink: 0;
          height: 280px;
          display: flex;
          flex-direction: column;
          min-height: 0;
        }
        .portfolio-tabs {
          display: flex;
          gap: 8px;
        }
        .tab-btn {
          background: transparent;
          border: none;
          color: var(--text-muted);
          font-family: var(--font-main);
          font-weight: 500;
          font-size: 12px;
          cursor: pointer;
          padding: 4px 10px;
          border-radius: 6px;
          transition: all 0.2s;
        }
        .tab-btn:hover {
          color: var(--text-primary);
          background: rgba(255, 255, 255, 0.03);
        }
        .tab-btn.active {
          color: var(--color-accent);
          background: rgba(6, 182, 212, 0.1);
        }
        .portfolio-content {
          overflow-y: auto;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .portfolio-summary-card {
          background: rgba(0, 0, 0, 0.2);
          border: 1px solid var(--border-color);
          border-radius: 12px;
          padding: 12px 20px;
          display: flex;
          justify-content: space-between;
          gap: 16px;
          flex-shrink: 0;
        }
        .summary-col {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .summary-label {
          font-size: 10px;
          color: var(--text-muted);
          text-transform: uppercase;
        }
        .summary-val {
          font-size: 16px;
          font-weight: 700;
          color: var(--text-primary);
        }
        .pl-percent {
          font-size: 11px;
          margin-left: 6px;
          font-weight: 500;
        }
        .empty-portfolio {
          text-align: center;
          color: var(--text-muted);
          font-size: 12px;
          padding: 30px 10px;
        }
        .holdings-list-wrapper, .transaction-history-wrapper {
          flex-grow: 1;
          overflow-y: auto;
          min-height: 0;
        }
        .portfolio-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 11px;
        }
        .portfolio-table th {
          text-align: left;
          color: var(--text-muted);
          font-weight: 600;
          padding: 8px 10px;
          border-bottom: 1px solid var(--border-color);
        }
        .portfolio-table td {
          padding: 8px 10px;
          border-bottom: 1px solid rgba(255, 255, 255, 0.02);
          vertical-align: middle;
        }
        .portfolio-table tr:hover td {
          background: rgba(255, 255, 255, 0.01);
        }
        .txt-right {
          text-align: right !important;
        }
        .ticker-cell {
          font-weight: 700;
          color: #fff;
          font-family: var(--font-display);
        }
        .text-buy { color: var(--color-buy) !important; }
        .text-sell { color: var(--color-sell) !important; }
        
        .trade-type-badge {
          font-size: 9px;
          font-weight: bold;
          padding: 2px 6px;
          border-radius: 4px;
        }
        .trade-type-badge.buy {
          background: rgba(16, 185, 129, 0.15);
          color: var(--color-buy);
        }
        .trade-type-badge.sell {
          background: rgba(244, 63, 94, 0.15);
          color: var(--color-sell);
        }
        .executor-badge {
          font-size: 9px;
          padding: 2px 6px;
          border-radius: 4px;
        }
        .executor-badge.user {
          background: rgba(255, 255, 255, 0.05);
          color: var(--text-secondary);
        }
        .executor-badge.ai {
          background: rgba(6, 182, 212, 0.1);
          color: var(--color-accent);
          border: 1px solid rgba(6, 182, 212, 0.2);
        }
        .lock-tag {
          display: inline-flex;
          align-items: center;
          gap: 2px;
          margin-left: 6px;
          padding: 1px 5px;
          border-radius: 4px;
          background: rgba(234, 179, 8, 0.12);
          color: #facc15;
          font-size: 9px;
          font-weight: 600;
        }
      `}</style>
    </div>
  );
}
