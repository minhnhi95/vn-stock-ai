import { useEffect, useMemo, useRef, useState } from 'react';
import { createChart, ColorType, CrosshairMode, LineStyle } from 'lightweight-charts';

/**
 * Biểu đồ kỹ thuật 3 khung: giá + khối lượng, RSI, MACD.
 *
 * lightweight-charts v4 chưa có pane nội bộ (đó là v5), nên mỗi khung là một
 * chart riêng, đồng bộ với nhau qua timeScale + crosshair. Thang giá được ép
 * cùng bề rộng tối thiểu để trục thời gian của 3 khung thẳng hàng.
 */

const UP = '#10b981';
const DOWN = '#f43f5e';
const ACCENT = '#06b6d4';
const VIOLET = '#8b5cf6';
const AMBER = '#f59e0b';
const AXIS = '#94a3b8';
const GRID = 'rgba(255, 255, 255, 0.03)';
const BORDER = 'rgba(255, 255, 255, 0.08)';

// Bề rộng cố định cho thang giá — nếu để tự co, 3 khung sẽ lệch trục thời gian.
const PRICE_SCALE_WIDTH = 68;

const baseOptions = (height) => ({
  layout: {
    background: { type: ColorType.Solid, color: 'transparent' },
    textColor: AXIS,
    fontSize: 11,
    fontFamily: "'Plus Jakarta Sans', sans-serif",
  },
  grid: {
    vertLines: { color: GRID },
    horzLines: { color: GRID },
  },
  crosshair: {
    mode: CrosshairMode.Normal,
    vertLine: { color: ACCENT, width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#0f172a' },
    horzLine: { color: ACCENT, width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#0f172a' },
  },
  rightPriceScale: { borderColor: BORDER, minimumWidth: PRICE_SCALE_WIDTH },
  timeScale: { borderColor: BORDER, timeVisible: false, secondsVisible: false },
  handleScale: { axisPressedMouseMove: { price: false } },
  height,
});

const fmtPrice = (v) =>
  v === null || v === undefined ? '—' : Math.round(Number(v)).toLocaleString();

const fmtVolume = (v) => {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return String(n);
};

const fmtNum = (v, digits = 2) =>
  v === null || v === undefined ? '—' : Number(v).toFixed(digits);

export default function StockChart({ data, symbol }) {
  const priceRef = useRef(null);
  const rsiRef = useRef(null);
  const macdRef = useRef(null);
  const chartsRef = useRef({});
  const seriesRef = useRef({});
  const syncingRef = useRef(false);
  const signatureRef = useRef(null);

  const [showRsi, setShowRsi] = useState(true);
  const [showMacd, setShowMacd] = useState(true);
  // Nến được crosshair trỏ vào; null = hiển thị nến cuối cùng.
  const [hovered, setHovered] = useState(null);

  const bars = useMemo(() => (Array.isArray(data) ? data : []), [data]);
  const lastBar = bars.length ? bars[bars.length - 1] : null;
  const readout = hovered || lastBar;
  const prevClose = useMemo(() => {
    if (!readout) return null;
    const i = bars.findIndex((b) => b.time === readout.time);
    return i > 0 ? bars[i - 1].close : null;
  }, [bars, readout]);

  const changePct =
    readout && prevClose ? ((readout.close - prevClose) / prevClose) * 100 : null;

  // ---- Dựng chart (chạy lại khi bật/tắt khung phụ vì số chart thay đổi) ----
  useEffect(() => {
    if (!priceRef.current) return undefined;

    const priceChart = createChart(priceRef.current, {
      ...baseOptions(priceRef.current.clientHeight || 320),
      timeScale: { borderColor: BORDER, timeVisible: false, visible: !showRsi && !showMacd },
    });

    const candles = priceChart.addCandlestickSeries({
      upColor: UP,
      downColor: DOWN,
      borderUpColor: UP,
      borderDownColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
      priceFormat: { type: 'price', precision: 0, minMove: 1 },
    });
    const ema20 = priceChart.addLineSeries({ color: ACCENT, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false });
    const ema50 = priceChart.addLineSeries({ color: VIOLET, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false });
    const ema200 = priceChart.addLineSeries({ color: AMBER, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false });

    // Khối lượng nằm chung khung giá nhưng thang riêng, ép xuống 22% dưới cùng.
    const volume = priceChart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
      lastValueVisible: false,
      priceLineVisible: false,
    });
    priceChart
      .priceScale('volume')
      .applyOptions({ scaleMargins: { top: 0.78, bottom: 0 }, visible: false });
    priceChart.priceScale('right').applyOptions({ scaleMargins: { top: 0.06, bottom: 0.26 } });

    const charts = { price: priceChart };
    const series = { candles, ema20, ema50, ema200, volume };

    if (showRsi && rsiRef.current) {
      const rsiChart = createChart(rsiRef.current, {
        ...baseOptions(rsiRef.current.clientHeight || 96),
        timeScale: { borderColor: BORDER, timeVisible: false, visible: !showMacd },
      });
      const rsi = rsiChart.addLineSeries({ color: ACCENT, lineWidth: 1.5, priceLineVisible: false });
      // Vùng quá mua/quá bán — mốc mọi nhà đầu tư đọc RSI đều nhìn.
      rsi.createPriceLine({ price: 70, color: DOWN, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '' });
      rsi.createPriceLine({ price: 30, color: UP, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '' });
      rsiChart.priceScale('right').applyOptions({ autoScale: false, minimumWidth: PRICE_SCALE_WIDTH });
      rsi.applyOptions({ autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) });
      charts.rsi = rsiChart;
      series.rsi = rsi;
    }

    if (showMacd && macdRef.current) {
      const macdChart = createChart(macdRef.current, {
        ...baseOptions(macdRef.current.clientHeight || 96),
        timeScale: { borderColor: BORDER, timeVisible: false, visible: true },
      });
      const hist = macdChart.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
      const macdLine = macdChart.addLineSeries({ color: ACCENT, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false });
      const signalLine = macdChart.addLineSeries({ color: AMBER, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false });
      charts.macd = macdChart;
      series.macdHist = hist;
      series.macdLine = macdLine;
      series.signalLine = signalLine;
    }

    chartsRef.current = charts;
    seriesRef.current = series;
    signatureRef.current = null; // buộc nạp lại dữ liệu cho instance mới

    // ---- Đồng bộ vùng nhìn giữa các khung ----
    const list = Object.values(charts);
    const unsubs = list.map((chart) => {
      const handler = (range) => {
        if (!range || syncingRef.current) return;
        syncingRef.current = true;
        list.forEach((other) => {
          if (other !== chart) other.timeScale().setVisibleLogicalRange(range);
        });
        syncingRef.current = false;
      };
      chart.timeScale().subscribeVisibleLogicalRangeChange(handler);
      return () => chart.timeScale().unsubscribeVisibleLogicalRangeChange(handler);
    });

    // ---- Đồng bộ crosshair + cập nhật ô đọc số ----
    const crosshairUnsubs = list.map((chart) => {
      const handler = (param) => {
        if (!param || param.time === undefined) {
          setHovered(null);
          list.forEach((other) => other !== chart && other.clearCrosshairPosition());
          return;
        }
        setHovered(bars.find((b) => b.time === param.time) || null);
        list.forEach((other) => {
          if (other === chart) return;
          const target =
            other === charts.rsi ? series.rsi : other === charts.macd ? series.macdLine : series.candles;
          if (target) other.setCrosshairPosition(0, param.time, target);
        });
      };
      chart.subscribeCrosshairMove(handler);
      return () => chart.unsubscribeCrosshairMove(handler);
    });

    const handleResize = () => {
      if (priceRef.current) {
        priceChart.applyOptions({
          width: priceRef.current.clientWidth,
          height: priceRef.current.clientHeight,
        });
      }
      if (charts.rsi && rsiRef.current) {
        charts.rsi.applyOptions({ width: rsiRef.current.clientWidth, height: rsiRef.current.clientHeight });
      }
      if (charts.macd && macdRef.current) {
        charts.macd.applyOptions({ width: macdRef.current.clientWidth, height: macdRef.current.clientHeight });
      }
    };
    handleResize();

    // Panel co giãn theo layout chứ không chỉ theo cửa sổ — dùng ResizeObserver.
    const observer = new ResizeObserver(handleResize);
    observer.observe(priceRef.current);
    window.addEventListener('resize', handleResize);

    return () => {
      observer.disconnect();
      window.removeEventListener('resize', handleResize);
      unsubs.forEach((fn) => fn());
      crosshairUnsubs.forEach((fn) => fn());
      list.forEach((chart) => chart.remove());
      chartsRef.current = {};
      seriesRef.current = {};
      signatureRef.current = null;
    };
    // `bars` cố tình không nằm trong deps: crosshair handler đọc qua closure và
    // dựng lại toàn bộ chart mỗi lần giá nhích 1 tick sẽ giật rất nặng.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showRsi, showMacd]);

  // ---- Nạp dữ liệu ----
  useEffect(() => {
    const { candles, ema20, ema50, ema200, volume, rsi, macdHist, macdLine, signalLine } =
      seriesRef.current;
    if (!candles || !bars.length) return;

    const firstTime = bars[0].time;
    const lastTime = bars[bars.length - 1].time;
    const signature = `${symbol}|${firstTime}|${lastTime}|${bars.length}`;

    if (signature === signatureRef.current) {
      // Cùng dải dữ liệu -> chỉ là tick giá mới, update nến cuối cho mượt.
      const bar = bars[bars.length - 1];
      candles.update({ time: bar.time, open: bar.open, high: bar.high, low: bar.low, close: bar.close });
      if (volume && bar.volume != null) {
        volume.update({
          time: bar.time,
          value: bar.volume,
          color: bar.close >= bar.open ? 'rgba(16,185,129,0.45)' : 'rgba(244,63,94,0.45)',
        });
      }
      return;
    }

    const line = (key) =>
      bars.filter((b) => b[key] !== null && b[key] !== undefined).map((b) => ({ time: b.time, value: b[key] }));

    candles.setData(
      bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })),
    );
    ema20.setData(line('ema20'));
    ema50.setData(line('ema50'));
    ema200.setData(line('ema200'));
    volume.setData(
      bars
        .filter((b) => b.volume !== null && b.volume !== undefined)
        .map((b) => ({
          time: b.time,
          value: b.volume,
          color: b.close >= b.open ? 'rgba(16,185,129,0.45)' : 'rgba(244,63,94,0.45)',
        })),
    );
    if (rsi) rsi.setData(line('rsi'));
    if (macdLine) macdLine.setData(line('macd'));
    if (signalLine) signalLine.setData(line('signal'));
    if (macdHist) {
      macdHist.setData(
        bars
          .filter((b) => b.hist !== null && b.hist !== undefined)
          .map((b) => ({
            time: b.time,
            value: b.hist,
            color: b.hist >= 0 ? 'rgba(16,185,129,0.6)' : 'rgba(244,63,94,0.6)',
          })),
      );
    }

    Object.values(chartsRef.current).forEach((chart) => chart.timeScale().fitContent());
    signatureRef.current = signature;
  }, [bars, symbol, showRsi, showMacd]);

  const up = changePct === null ? null : changePct >= 0;

  return (
    <div className="sc-wrap">
      <div className="sc-toolbar">
        <div className="sc-ohlc">
          <span className="sc-ohlc-sym">{symbol}</span>
          <span>
            M <b>{fmtPrice(readout?.open)}</b>
          </span>
          <span>
            C <b>{fmtPrice(readout?.high)}</b>
          </span>
          <span>
            T <b>{fmtPrice(readout?.low)}</b>
          </span>
          <span>
            Đ{' '}
            <b className={up === null ? '' : up ? 'sc-up' : 'sc-down'}>{fmtPrice(readout?.close)}</b>
          </span>
          {changePct !== null ? (
            <span className={up ? 'sc-up' : 'sc-down'}>
              {up ? '+' : ''}
              {changePct.toFixed(2)}%
            </span>
          ) : null}
          <span className="sc-ohlc-vol">KL {fmtVolume(readout?.volume)}</span>
        </div>
        <div className="sc-right">
          <span className="sc-legend">
            <span className="sc-key"><i style={{ background: ACCENT }} />EMA20</span>
            <span className="sc-key"><i style={{ background: VIOLET }} />EMA50</span>
            <span className="sc-key"><i style={{ background: AMBER }} />EMA200</span>
          </span>
          <span className="sc-toggles">
            <button
              type="button"
              className={`sc-toggle ${showRsi ? 'on' : ''}`}
              onClick={() => setShowRsi((v) => !v)}
              aria-pressed={showRsi}
            >
              RSI
            </button>
            <button
              type="button"
              className={`sc-toggle ${showMacd ? 'on' : ''}`}
              onClick={() => setShowMacd((v) => !v)}
              aria-pressed={showMacd}
            >
              MACD
            </button>
          </span>
        </div>
      </div>

      <div className="sc-pane sc-pane-price" ref={priceRef} />
      {showRsi ? (
        <div className="sc-sub">
          <span className="sc-sub-label">
            RSI(14) <b>{fmtNum(readout?.rsi, 1)}</b>
          </span>
          <div className="sc-pane sc-pane-sub" ref={rsiRef} />
        </div>
      ) : null}
      {showMacd ? (
        <div className="sc-sub">
          <span className="sc-sub-label">
            MACD <b>{fmtNum(readout?.macd, 1)}</b> · Signal <b>{fmtNum(readout?.signal, 1)}</b>
          </span>
          <div className="sc-pane sc-pane-sub" ref={macdRef} />
        </div>
      ) : null}

      <style>{`
        .sc-wrap {
          display: flex;
          flex-direction: column;
          width: 100%;
          height: 100%;
          min-height: 0;
        }
        .sc-toolbar {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          flex-wrap: wrap;
          padding: 0 4px 5px;
          flex: 0 0 auto;
        }
        .sc-ohlc {
          display: flex;
          align-items: center;
          gap: 10px;
          flex-wrap: wrap;
          font-size: 11px;
          color: var(--text-muted);
          font-variant-numeric: tabular-nums;
        }
        .sc-ohlc b { color: var(--text-primary); font-weight: 600; }
        .sc-ohlc-sym {
          font-family: var(--font-display);
          font-weight: 700;
          color: var(--text-primary);
          letter-spacing: 0.5px;
        }
        .sc-ohlc-vol { color: var(--text-muted); }
        .sc-up { color: var(--color-buy) !important; }
        .sc-down { color: var(--color-sell) !important; }
        .sc-toggles { display: inline-flex; gap: 6px; }
        .sc-toggle {
          font-size: 10px;
          letter-spacing: 0.5px;
          padding: 3px 9px;
          border-radius: 999px;
          border: 1px solid var(--border-color);
          background: transparent;
          color: var(--text-muted);
          cursor: pointer;
        }
        .sc-toggle.on { border-color: var(--color-accent); color: var(--color-accent); }
        .sc-right {
          display: flex;
          align-items: center;
          gap: 12px;
          flex-wrap: wrap;
        }
        .sc-legend {
          display: inline-flex;
          gap: 10px;
          flex-wrap: wrap;
          font-size: 10px;
          color: var(--text-muted);
        }
        .sc-key { display: inline-flex; align-items: center; gap: 4px; }
        .sc-key i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
        .sc-pane { width: 100%; }
        .sc-pane-price { flex: 1 1 auto; min-height: 300px; }
        .sc-sub { position: relative; flex: 0 0 auto; }
        .sc-pane-sub { height: 96px; }
        .sc-sub-label {
          position: absolute;
          top: 2px;
          left: 8px;
          z-index: 3;
          font-size: 10px;
          color: var(--text-muted);
          font-variant-numeric: tabular-nums;
          pointer-events: none;
        }
        .sc-sub-label b { color: var(--text-primary); font-weight: 600; }
      `}</style>
    </div>
  );
}
