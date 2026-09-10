import { useEffect, useState, useCallback } from 'react';
import { Globe2, Grid3x3, RefreshCw, TrendingUp, TrendingDown } from 'lucide-react';

// Backend trả giá trị khối ngoại bằng VND nguyên (vd 21_131_669_200), phải quy
// về tỷ trước khi gắn hậu tố "tỷ" — nếu không sẽ hiện "21131669200.0 tỷ".
const fmtBillion = (v) => {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return 'N/A';
  const num = Number(v);
  const sign = num > 0 ? '+' : num < 0 ? '-' : '';
  const abs = Math.abs(num);
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(2)} tỷ`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(1)} tr`;
  return `${sign}${abs.toLocaleString()} đ`;
};

const fmtPct = (v) => {
  if (v === null || v === undefined || Number.isNaN(v)) return 'N/A';
  const num = Number(v);
  const sign = num >= 0 ? '+' : '';
  return `${sign}${num.toFixed(2)}%`;
};

const fmtTime = (iso) => {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const mo = String(d.getMonth() + 1).padStart(2, '0');
    return `${hh}:${mm} ${dd}/${mo}`;
  } catch {
    return iso;
  }
};

const heatmapTone = (pct) => {
  if (pct === null || pct === undefined || Number.isNaN(pct)) return 'flat';
  const p = Number(pct);
  if (p > 3) return 'buy-strong';
  if (p > 0) return 'buy-soft';
  if (p < -3) return 'sell-strong';
  if (p < 0) return 'sell-soft';
  return 'flat';
};

const fmtShares = (v) => {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return 'N/A';
  const num = Number(v);
  const sign = num > 0 ? '+' : num < 0 ? '-' : '';
  const abs = Math.abs(num);
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(2)}M CP`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(0)}K CP`;
  return `${sign}${abs.toLocaleString()} CP`;
};

const ForeignRow = ({ item, side }) => {
  // price_board không phải lúc nào cũng trả cột giá trị; khi thiếu, backend xếp
  // hạng theo khối lượng. Hiện đúng thứ đang có — trước đây rơi về 0 nên bảng
  // toàn "0 đ" dù khối ngoại mua ròng hàng triệu cổ phiếu.
  const value = item?.net_value ?? item?.value ?? item?.net ?? null;
  const volume = item?.net_volume ?? null;
  const symbol = item?.symbol || item?.ticker || '---';
  const name = item?.name || item?.company_name || null;
  const isBuy = side === 'buy';
  const hasValue = value !== null && value !== undefined && Number(value) !== 0;
  return (
    <div className="mp-foreign-row">
      <div className="mp-foreign-left">
        <span className="mp-foreign-symbol">{symbol}</span>
        {name ? <span className="mp-foreign-name">{name}</span> : null}
      </div>
      <span
        className={`mp-foreign-badge ${isBuy ? 'buy' : 'sell'}`}
        title={
          hasValue && volume !== null
            ? `${fmtShares(volume)} · ${fmtBillion(value)}`
            : undefined
        }
      >
        {hasValue ? fmtBillion(value) : fmtShares(volume)}
      </span>
    </div>
  );
};

const SectorBox = ({ item }) => {
  const name = item?.name || item?.sector || item?.industry || '---';
  // Backend trả `avg_change_pct`; các tên còn lại là dự phòng cho schema cũ.
  const pct = item?.avg_change_pct ?? item?.change_pct ?? item?.pct ?? item?.change ?? null;
  // Trung bình chỉ tính trên vài mã đại diện (rổ VN100), không phải cả ngành —
  // hiện luôn tên mã để con số không bị đọc nhầm thành chỉ số ngành.
  const used = Array.isArray(item?.symbols_used) ? item.symbols_used : [];
  const tone = heatmapTone(pct);
  return (
    <div className={`mp-sector-box mp-tone-${tone}`}>
      <div className="mp-sector-name">{name}</div>
      <div className="mp-sector-pct">{fmtPct(pct)}</div>
      {used.length ? (
        <div className="mp-sector-count" title={`Trung bình của ${used.join(', ')}`}>
          {used.join(' · ')}
        </div>
      ) : null}
    </div>
  );
};

export default function MarketPanel({ apiBase }) {
  const [foreign, setForeign] = useState(null);
  const [sectors, setSectors] = useState(null);
  const [foreignLoading, setForeignLoading] = useState(false);
  const [sectorsLoading, setSectorsLoading] = useState(false);
  const [foreignError, setForeignError] = useState(null);
  const [sectorsError, setSectorsError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  const loadForeign = useCallback(async () => {
    if (!apiBase) return;
    setForeignLoading(true);
    setForeignError(null);
    try {
      const res = await fetch(`${apiBase}/foreign/top`);
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
      setForeign(data);
    } catch (err) {
      setForeignError(err.message || 'Lỗi tải dữ liệu khối ngoại');
      setForeign(null);
    } finally {
      setForeignLoading(false);
    }
  }, [apiBase]);

  const loadSectors = useCallback(async () => {
    if (!apiBase) return;
    setSectorsLoading(true);
    setSectorsError(null);
    try {
      const res = await fetch(`${apiBase}/sectors/heatmap`);
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
      setSectors(data);
    } catch (err) {
      setSectorsError(err.message || 'Lỗi tải heatmap ngành');
      setSectors(null);
    } finally {
      setSectorsLoading(false);
    }
  }, [apiBase]);

  const refreshAll = useCallback(async () => {
    await Promise.all([loadForeign(), loadSectors()]);
    setLastUpdated(new Date().toISOString());
  }, [loadForeign, loadSectors]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  // Backend trả `top_net_buy` / `top_net_sell`; các tên còn lại là dự phòng.
  const topBuy = foreign?.top_net_buy || foreign?.top_buy || foreign?.buy || [];
  const topSell = foreign?.top_net_sell || foreign?.top_sell || foreign?.sell || [];
  const sectorList = Array.isArray(sectors)
    ? sectors
    : sectors?.sectors || sectors?.heatmap || sectors?.items || [];

  const serverUpdated = foreign?.last_updated || sectors?.last_updated;
  const updatedDisplay = fmtTime(serverUpdated || lastUpdated);
  const isRefreshing = foreignLoading || sectorsLoading;

  return (
    <div className="glass-panel mp-panel">
      <div className="panel-header">
        <div className="panel-title">
          <Globe2 size={16} className="text-accent" />
          <span>Toàn cảnh thị trường</span>
        </div>
        <div className="mp-header-right">
          {updatedDisplay ? (
            <span className="mp-updated">Cập nhật: {updatedDisplay}</span>
          ) : null}
          <button
            type="button"
            className="mp-refresh-btn"
            onClick={refreshAll}
            disabled={isRefreshing}
            title="Làm mới"
          >
            <RefreshCw size={12} className={isRefreshing ? 'mp-spin' : ''} />
            <span>Làm mới</span>
          </button>
        </div>
      </div>

      <div className="panel-content mp-grid">
        {/* Section 1: Khối ngoại */}
        <section className="mp-section">
          <header className="mp-section-header">
            <Globe2 size={13} className="text-accent" />
            <h3 className="mp-section-title">Khối ngoại hôm nay</h3>
          </header>

          {foreignError ? (
            <div className="mp-error">{foreignError}</div>
          ) : foreignLoading && !foreign ? (
            <div className="mp-loading">Đang tải dữ liệu khối ngoại...</div>
          ) : (!topBuy.length && !topSell.length) ? (
            <div className="mp-empty">Chưa có dữ liệu khối ngoại cho phiên hôm nay.</div>
          ) : (
            <div className="mp-foreign-cols">
              <div className="mp-foreign-col">
                <div className="mp-foreign-col-head buy">
                  <TrendingUp size={11} />
                  <span>Top mua ròng</span>
                </div>
                {topBuy.length ? (
                  topBuy.map((it, i) => (
                    <ForeignRow key={`buy-${it.symbol || i}`} item={it} side="buy" />
                  ))
                ) : (
                  <div className="mp-mini-empty">Chưa có mã mua ròng.</div>
                )}
              </div>
              <div className="mp-foreign-col">
                <div className="mp-foreign-col-head sell">
                  <TrendingDown size={11} />
                  <span>Top bán ròng</span>
                </div>
                {topSell.length ? (
                  topSell.map((it, i) => (
                    <ForeignRow key={`sell-${it.symbol || i}`} item={it} side="sell" />
                  ))
                ) : (
                  <div className="mp-mini-empty">Chưa có mã bán ròng.</div>
                )}
              </div>
            </div>
          )}
        </section>

        {/* Section 2: Sector heatmap */}
        <section className="mp-section">
          <header className="mp-section-header">
            <Grid3x3 size={13} className="text-accent" />
            <h3 className="mp-section-title">Sector Heatmap</h3>
          </header>

          {sectorsError ? (
            <div className="mp-error">{sectorsError}</div>
          ) : sectorsLoading && !sectors ? (
            <div className="mp-loading">Đang tải heatmap ngành...</div>
          ) : !sectorList.length ? (
            <div className="mp-empty">Chưa có dữ liệu ngành.</div>
          ) : (
            <div className="mp-heatmap">
              {sectorList.map((s, i) => (
                <SectorBox key={s.name || s.sector || i} item={s} />
              ))}
            </div>
          )}
        </section>
      </div>

      <style>{`
        .mp-header-right {
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .mp-updated {
          font-size: 10px;
          color: var(--text-muted);
          font-family: var(--font-display);
        }
        .mp-refresh-btn {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          background: rgba(6, 182, 212, 0.12);
          border: 1px solid rgba(6, 182, 212, 0.3);
          color: var(--color-accent);
          padding: 3px 9px;
          border-radius: 4px;
          font-size: 10px;
          font-weight: 600;
          cursor: pointer;
          transition: background 0.15s;
        }
        .mp-refresh-btn:hover:not(:disabled) {
          background: rgba(6, 182, 212, 0.22);
        }
        .mp-refresh-btn:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }
        .mp-spin {
          animation: mp-spin 1s linear infinite;
        }
        @keyframes mp-spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }

        /* Panel này ở trong rail 320px trên desktop nhưng full-width trên mobile.
           Chia cột theo viewport (như trước) khiến rail 320px bị xẻ đôi thành hai
           cột 140px — không đủ chỗ cho cả mã lẫn giá trị. Dùng container query. */
        .mp-panel { container-type: inline-size; }
        .mp-grid {
          display: grid;
          grid-template-columns: 1fr;
          gap: 14px;
        }
        @container (min-width: 640px) {
          .mp-grid { grid-template-columns: 1fr 1fr; }
        }

        .mp-section {
          display: flex;
          flex-direction: column;
          gap: 8px;
          background: rgba(0, 0, 0, 0.18);
          border: 1px solid var(--border-color);
          border-radius: 10px;
          padding: 10px;
        }
        .mp-section-header {
          display: flex;
          align-items: center;
          gap: 6px;
          padding-bottom: 4px;
          border-bottom: 1px solid var(--border-color);
        }
        .mp-section-title {
          margin: 0;
          font-size: 11px;
          font-weight: 700;
          color: var(--text-primary);
          text-transform: uppercase;
          letter-spacing: 0.6px;
        }

        .mp-loading, .mp-empty, .mp-mini-empty {
          text-align: center;
          font-size: 11px;
          color: var(--text-muted);
          padding: 16px 8px;
        }
        .mp-mini-empty { padding: 8px; font-size: 10px; }
        .mp-error {
          background: rgba(244, 63, 94, 0.1);
          border: 1px solid rgba(244, 63, 94, 0.3);
          color: #fda4af;
          padding: 8px 10px;
          border-radius: 6px;
          font-size: 11px;
        }

        /* Khối ngoại */
        /* Panel này nằm trong rail hẹp (~230px) ở desktop nhưng chiếm nguyên
           chiều rộng trên mobile — quyết định số cột theo bề rộng CONTAINER chứ
           không theo viewport, nếu không mã CK bị bóp còn 14px và cụt chữ. */
        .mp-section { container-type: inline-size; }
        .mp-foreign-cols {
          display: grid;
          grid-template-columns: 1fr;
          gap: 10px;
        }
        @container (min-width: 420px) {
          .mp-foreign-cols { grid-template-columns: 1fr 1fr; gap: 8px; }
        }
        .mp-foreign-col {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .mp-foreign-col-head {
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: 10px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          padding: 4px 6px;
          border-radius: 4px;
        }
        .mp-foreign-col-head.buy {
          background: rgba(16, 185, 129, 0.1);
          color: var(--color-buy);
        }
        .mp-foreign-col-head.sell {
          background: rgba(244, 63, 94, 0.1);
          color: var(--color-sell);
        }
        .mp-foreign-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 6px;
          min-width: 0;
          padding: 6px 8px;
          background: rgba(0, 0, 0, 0.25);
          border: 1px solid var(--border-color);
          border-radius: 6px;
        }
        .mp-foreign-left {
          display: flex;
          flex-direction: column;
          gap: 1px;
          min-width: 0;
          flex-grow: 1;
        }
        .mp-foreign-symbol {
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 12px;
          color: var(--text-primary);
          letter-spacing: 0.4px;
          flex: 0 0 auto;
          white-space: nowrap;
        }
        .mp-foreign-name {
          font-size: 10px;
          color: var(--text-muted);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .mp-foreign-badge {
          flex-shrink: 0;
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 11px;
          padding: 3px 7px;
          border-radius: 4px;
        }
        .mp-foreign-badge.buy {
          background: rgba(16, 185, 129, 0.12);
          color: var(--color-buy);
          border: 1px solid rgba(16, 185, 129, 0.3);
        }
        .mp-foreign-badge.sell {
          background: rgba(244, 63, 94, 0.12);
          color: var(--color-sell);
          border: 1px solid rgba(244, 63, 94, 0.3);
        }

        /* Sector heatmap */
        .mp-heatmap {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
          gap: 6px;
        }
        .mp-sector-box {
          display: flex;
          flex-direction: column;
          gap: 2px;
          padding: 8px 10px;
          border-radius: 6px;
          border: 1px solid var(--border-color);
          background: rgba(0, 0, 0, 0.25);
          transition: transform 0.15s;
        }
        .mp-sector-box:hover {
          transform: translateY(-1px);
        }
        .mp-sector-name {
          font-size: 11px;
          font-weight: 600;
          color: var(--text-primary);
          line-height: 1.25;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .mp-sector-pct {
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 13px;
        }
        .mp-sector-count {
          font-size: 9px;
          color: var(--text-muted);
          text-transform: uppercase;
          letter-spacing: 0.4px;
        }

        .mp-tone-buy-strong {
          background: rgba(16, 185, 129, 0.28);
          border-color: rgba(16, 185, 129, 0.55);
        }
        .mp-tone-buy-strong .mp-sector-pct { color: #34d399; }
        .mp-tone-buy-soft {
          background: rgba(16, 185, 129, 0.1);
          border-color: rgba(16, 185, 129, 0.28);
        }
        .mp-tone-buy-soft .mp-sector-pct { color: var(--color-buy); }
        .mp-tone-sell-soft {
          background: rgba(244, 63, 94, 0.1);
          border-color: rgba(244, 63, 94, 0.28);
        }
        .mp-tone-sell-soft .mp-sector-pct { color: var(--color-sell); }
        .mp-tone-sell-strong {
          background: rgba(244, 63, 94, 0.28);
          border-color: rgba(244, 63, 94, 0.55);
        }
        .mp-tone-sell-strong .mp-sector-pct { color: #fb7185; }
        .mp-tone-flat .mp-sector-pct { color: var(--text-muted); }
      `}</style>
    </div>
  );
}
