import React, { useEffect, useRef } from 'react';
import { createChart, ColorType } from 'lightweight-charts';

export default function StockChart({ data, symbol }) {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const ema20SeriesRef = useRef(null);
  const ema50SeriesRef = useRef(null);
  const lastDataSignatureRef = useRef(null);

  // Create chart once on mount; destroy on unmount.
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#94a3b8',
        fontSize: 12,
        fontFamily: "'Plus Jakarta Sans', sans-serif",
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.03)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.03)' },
      },
      crosshair: {
        mode: 1,
        vertLine: { color: '#06b6d4', width: 1, style: 3 },
        horzLine: { color: '#06b6d4', width: 1, style: 3 },
      },
      rightPriceScale: { borderColor: 'rgba(255, 255, 255, 0.08)' },
      timeScale: {
        borderColor: 'rgba(255, 255, 255, 0.08)',
        timeVisible: true,
        secondsVisible: false,
      },
      width: chartContainerRef.current.clientWidth,
      height: 380,
    });

    chartRef.current = chart;
    candleSeriesRef.current = chart.addCandlestickSeries({
      upColor: '#10b981',
      downColor: '#f43f5e',
      borderUpColor: '#10b981',
      borderDownColor: '#f43f5e',
      wickUpColor: '#10b981',
      wickDownColor: '#f43f5e',
    });
    ema20SeriesRef.current = chart.addLineSeries({
      color: '#06b6d4',
      lineWidth: 1.5,
      title: 'EMA 20',
    });
    ema50SeriesRef.current = chart.addLineSeries({
      color: '#8b5cf6',
      lineWidth: 1.5,
      title: 'EMA 50',
    });

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      ema20SeriesRef.current = null;
      ema50SeriesRef.current = null;
      lastDataSignatureRef.current = null;
    };
  }, []);

  // Apply data: full-reset when signature changes, tick-update otherwise.
  useEffect(() => {
    if (!chartRef.current || !candleSeriesRef.current || !data || data.length === 0) return;

    const firstTime = data[0].time;
    const lastTime = data[data.length - 1].time;
    const signature = `${symbol}|${firstTime}|${lastTime}|${data.length}`;
    const prevSignature = lastDataSignatureRef.current;

    if (signature !== prevSignature) {
      const candles = data.map(d => ({
        time: d.time,
        open: d.open,
        high: d.high,
        low: d.low,
        close: d.close,
      }));
      const ema20Data = data
        .filter(d => d.ema20 !== null && d.ema20 !== undefined)
        .map(d => ({ time: d.time, value: d.ema20 }));
      const ema50Data = data
        .filter(d => d.ema50 !== null && d.ema50 !== undefined)
        .map(d => ({ time: d.time, value: d.ema50 }));

      candleSeriesRef.current.setData(candles);
      ema20SeriesRef.current.setData(ema20Data);
      ema50SeriesRef.current.setData(ema50Data);
      chartRef.current.timeScale().fitContent();
      lastDataSignatureRef.current = signature;
      return;
    }

    const lastBar = data[data.length - 1];
    candleSeriesRef.current.update({
      time: lastBar.time,
      open: lastBar.open,
      high: lastBar.high,
      low: lastBar.low,
      close: lastBar.close,
    });
  }, [data, symbol]);

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      <div style={{ position: 'absolute', top: 8, left: 16, zIndex: 10, display: 'flex', gap: 12 }}>
        <div style={{ fontSize: '11px', color: '#64748b', display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ display: 'inline-block', width: 8, height: 8, backgroundColor: '#06b6d4', borderRadius: '50%' }}></span>
          EMA 20
        </div>
        <div style={{ fontSize: '11px', color: '#64748b', display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ display: 'inline-block', width: 8, height: 8, backgroundColor: '#8b5cf6', borderRadius: '50%' }}></span>
          EMA 50
        </div>
      </div>
      <div ref={chartContainerRef} style={{ width: '100%', height: '380px' }} />
    </div>
  );
}
