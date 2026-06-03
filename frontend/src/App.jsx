import React, { useState, useEffect, useRef } from 'react';
import { Search, TrendingUp, Sliders, Play, Square, Key, Bell, Compass, RefreshCw, BarChart2, Shield } from 'lucide-react';

// Components
import StockChart from './components/StockChart';
import AiAnalyst from './components/AiAnalyst';
import PortfolioTracker from './components/PortfolioTracker';
import Fundamentals from './components/Fundamentals';
import News from './components/News';
import BacktestModal from './components/BacktestModal';
import MarketPanel from './components/MarketPanel';
import AIScanner from './components/AIScanner';
import AlertsManager from './components/AlertsManager';
import CalendarPanel from './components/CalendarPanel';
import InsiderPanel from './components/InsiderPanel';
import PortfolioReview from './components/PortfolioReview';
import { Activity, Radar, Briefcase } from 'lucide-react';

// API endpoint: dev mặc định localhost; prod đặt VITE_API_BASE qua Vercel env.
// Bỏ trailing slash để không gây double-slash khi nối path.
const RAW_BASE = (import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8765').replace(/\/$/, '');
const API_BASE = `${RAW_BASE}/api`;

export default function App() {
  // Config & API Keys
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('gemini_api_key') || '');
  const [showKeyInput, setShowKeyInput] = useState(false);
  const [keyInputTemp, setKeyInputTemp] = useState(apiKey);

  // Stock Search
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [selectedStock, setSelectedStock] = useState({ symbol: 'FPT', name: 'Công ty Cổ phần FPT', exchange: 'HOSE' });

  // Data State
  const [chartData, setChartData] = useState([]);
  const [isChartLoading, setIsChartLoading] = useState(false);
  const [realtimePrice, setRealtimePrice] = useState(0);
  const [originalLastClose, setOriginalLastClose] = useState(0);
  const [priceChangePercent, setPriceChangePercent] = useState(0);

  // AI State
  const [aiAnalysis, setAiAnalysis] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [chatMessages, setChatMessages] = useState([]);
  const [isChatting, setIsChatting] = useState(false);

  // Paper Trading Portfolio State.
  // Server (SQLite) là source of truth. Frontend merge currentPrice (chỉ giữ ở client).
  const INITIAL_CAPITAL = 100000000;
  const T_PLUS_LOCK_MS = 2 * 24 * 3600 * 1000;
  const [portfolio, setPortfolio] = useState({
    cash: INITIAL_CAPITAL,
    holdings: []
  });
  const [transactionHistory, setTransactionHistory] = useState([]);
  const [isTrading, setIsTrading] = useState(false);
  const [isAutoTrading, setIsAutoTrading] = useState(false);
  const [tradingNotification, setTradingNotification] = useState(null);
  const [nowTick, setNowTick] = useState(Date.now()); // tick mỗi 30s để refresh trạng thái khóa T+

  // Risk guardrails (config qua UI).
  const [riskConfig, setRiskConfig] = useState({
    maxPositionPercent: 20,    // 1 mã tối đa 20% NAV
    dailyLossLimitPercent: 3,  // bot tự dừng khi NAV giảm > 3% so với đầu phiên
    botCashUsagePercent: 20,   // mỗi lệnh dùng 20% tiền mặt
  });
  const sessionStartNavRef = useRef(INITIAL_CAPITAL);
  const [botPaused, setBotPaused] = useState(false);

  // Buy/Sell Order Inputs
  const [tradeShares, setTradeShares] = useState(100);

  // Market status & fundamentals & news
  const [marketStatus, setMarketStatus] = useState({ status: 'CLOSED', reason: '...', is_open: false });
  const [fundamentals, setFundamentals] = useState(null);
  const [newsItems, setNewsItems] = useState([]);

  // Backtest modal
  const [showBacktest, setShowBacktest] = useState(false);
  const [showScanner, setShowScanner] = useState(false);
  const [showPortfolioReview, setShowPortfolioReview] = useState(false);

  // Fetch search results on mount or query change
  useEffect(() => {
    const delayDebounce = setTimeout(() => {
      fetchStocks(searchQuery);
    }, 300);
    return () => clearTimeout(delayDebounce);
  }, [searchQuery]);

  // Load stock chart data on selected stock change
  useEffect(() => {
    loadStockData(selectedStock.symbol);
    setAiAnalysis(null);
    setChatMessages([]);
  }, [selectedStock]);

  // Helper: merge currentPrice từ state cũ vào holdings từ server (server không lưu giá hiện tại).
  const mergePortfolioFromServer = (serverPortfolio, prevHoldings = []) => {
    const priceMap = new Map(prevHoldings.map(h => [h.symbol, h.currentPrice]));
    return {
      cash: serverPortfolio.cash,
      holdings: (serverPortfolio.holdings || []).map(h => ({
        ...h,
        currentPrice: priceMap.get(h.symbol) ?? h.avgPrice,
      })),
    };
  };

  // Load portfolio + transactions từ SQLite khi mở app.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/portfolio`);
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled) return;
        setPortfolio(prev => mergePortfolioFromServer(data.portfolio, prev.holdings));
        setTransactionHistory(data.transactions || []);
      } catch (e) {
        // im lặng - dùng state mặc định
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Poll market status mỗi 30s — chỉ điều phối, không tốn tài nguyên.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const res = await fetch(`${API_BASE}/market/status`);
        const data = await res.json();
        if (!cancelled) setMarketStatus(data);
      } catch (e) {
        // im lặng — không phá flow chính
      }
    };
    tick();
    const id = setInterval(tick, 30000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // Theo dõi tab visibility để pause polling khi user chuyển tab.
  const [isTabVisible, setIsTabVisible] = useState(() => !document.hidden);
  useEffect(() => {
    const onVis = () => setIsTabVisible(!document.hidden);
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, []);

  // Polling giá thật từ vnstock. Mỗi 5s khi mở cửa, mỗi 60s khi đóng cửa (giữ giá ổn định).
  // Pause hoàn toàn khi tab ẩn — tiết kiệm rate limit của vnstock.
  useEffect(() => {
    if (!selectedStock?.symbol || realtimePrice <= 0) return;
    if (!isTabVisible) return;

    let cancelled = false;
    const applyPrice = (newPrice) => {
      if (cancelled || !newPrice || newPrice <= 0) return;
      setRealtimePrice(newPrice);
      if (originalLastClose > 0) {
        setPriceChangePercent(((newPrice - originalLastClose) / originalLastClose) * 100);
      }
      setChartData(prevData => {
        if (prevData.length === 0) return prevData;
        const updated = [...prevData];
        const i = updated.length - 1;
        updated[i] = {
          ...updated[i],
          close: newPrice,
          high: Math.max(updated[i].high, newPrice),
          low: Math.min(updated[i].low, newPrice),
        };
        return updated;
      });
      setPortfolio(prev => ({
        ...prev,
        holdings: prev.holdings.map(h => h.symbol === selectedStock.symbol ? { ...h, currentPrice: newPrice } : h),
      }));
    };

    const fetchPrice = async () => {
      try {
        const res = await fetch(`${API_BASE}/stocks/realtime?symbol=${encodeURIComponent(selectedStock.symbol)}`);
        if (!res.ok) return;
        const data = await res.json();
        if (data?.price) applyPrice(Number(data.price));
      } catch (e) {
        // im lặng
      }
    };

    fetchPrice();
    const intervalMs = marketStatus.is_open ? 5000 : 60000;
    const id = setInterval(fetchPrice, intervalMs);
    return () => { cancelled = true; clearInterval(id); };
  }, [selectedStock, originalLastClose, marketStatus.is_open, isTabVisible]);

  // Fetch fundamentals + news khi đổi mã (cache backend)
  useEffect(() => {
    if (!selectedStock?.symbol) return;
    let cancelled = false;
    (async () => {
      try {
        const [fRes, nRes] = await Promise.all([
          fetch(`${API_BASE}/stocks/fundamentals?symbol=${encodeURIComponent(selectedStock.symbol)}`),
          fetch(`${API_BASE}/news?symbol=${encodeURIComponent(selectedStock.symbol)}&limit=5`),
        ]);
        if (!cancelled && fRes.ok) setFundamentals(await fRes.json());
        if (!cancelled && nRes.ok) {
          const data = await nRes.json();
          setNewsItems(data.items || []);
        }
      } catch (e) {
        // im lặng
      }
    })();
    return () => { cancelled = true; };
  }, [selectedStock]);

  // Tick mỗi 30s — cập nhật trạng thái T+ và làm tươi NAV daily-loss check.
  useEffect(() => {
    const id = setInterval(() => setNowTick(Date.now()), 30000);
    return () => clearInterval(id);
  }, []);

  // Snapshot NAV đầu phiên khi bật bot (để áp dụng daily loss limit).
  useEffect(() => {
    if (isAutoTrading) {
      sessionStartNavRef.current = computeNav(portfolio);
      setBotPaused(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAutoTrading]);

  // AI Auto-Trading Trigger Logic. Trigger ONCE per unique analysis + guardrails.
  const lastTradedAnalysisRef = useRef(null);

  // Reset ref khi đổi mã — tránh aiAnalysis cũ của mã trước trigger lệnh trên mã mới.
  useEffect(() => {
    lastTradedAnalysisRef.current = null;
  }, [selectedStock.symbol]);

  useEffect(() => {
    if (!isAutoTrading || botPaused) return;
    if (!aiAnalysis || !aiAnalysis.analysis) return;
    if (lastTradedAnalysisRef.current === aiAnalysis) return;
    if (!Number.isFinite(realtimePrice) || realtimePrice <= 0) return;
    if (!marketStatus.is_open) return; // không trade khi đóng cửa

    // Chỉ trade khi aiAnalysis là của mã đang xem (tránh stale signals).
    const targetSymbol = aiAnalysis.symbol;
    if (!targetSymbol || targetSymbol !== selectedStock.symbol) {
      lastTradedAnalysisRef.current = aiAnalysis;
      return;
    }

    // Guardrail: daily loss limit
    const nav = computeNav(portfolio);
    const startNav = sessionStartNavRef.current || nav;
    const dayPL = ((nav - startNav) / startNav) * 100;
    if (dayPL <= -riskConfig.dailyLossLimitPercent) {
      setBotPaused(true);
      showNotification(`[AI BOT] Tự dừng — NAV giảm ${dayPL.toFixed(2)}% (giới hạn ${-riskConfig.dailyLossLimitPercent}%).`, 'error');
      lastTradedAnalysisRef.current = aiAnalysis;
      return;
    }

    const rec = aiAnalysis.analysis.recommendation;
    const conf = aiAnalysis.analysis.confidence;
    if (conf < 80) {
      lastTradedAnalysisRef.current = aiAnalysis;
      return;
    }

    if (rec === 'STRONG_BUY' || rec === 'BUY') {
      const buyPower = portfolio.cash * (riskConfig.botCashUsagePercent / 100);
      const sharesToBuy = Math.floor(buyPower / realtimePrice);
      if (Number.isFinite(sharesToBuy) && sharesToBuy >= 10) {
        executeBuyOrder(targetSymbol, sharesToBuy, true);
      }
    } else if (rec === 'STRONG_SELL' || rec === 'SELL') {
      const holding = portfolio.holdings.find(h => h.symbol === targetSymbol);
      if (holding) {
        const sellable = availableSharesOf(holding);
        if (sellable > 0) executeSellOrder(targetSymbol, sellable, true);
      }
    }

    lastTradedAnalysisRef.current = aiAnalysis;
  }, [aiAnalysis, isAutoTrading, botPaused, realtimePrice, portfolio, selectedStock, marketStatus.is_open, riskConfig]);

  const fetchStocks = async (query) => {
    try {
      const res = await fetch(`${API_BASE}/stocks/search?query=${encodeURIComponent(query)}`);
      const data = await res.json();
      setSearchResults(data);
    } catch (e) {
      console.error('Error fetching stock list:', e);
    }
  };

  const loadStockData = async (symbol) => {
    setIsChartLoading(true);
    try {
      const res = await fetch(`${API_BASE}/stocks/historical?symbol=${encodeURIComponent(symbol)}`);
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Lỗi tải dữ liệu.');
      }
      const data = await res.json();
      
      setChartData(data.data);
      if (data.data.length > 0) {
        const lastClose = data.data[data.data.length - 1].close;
        setRealtimePrice(lastClose);
        setOriginalLastClose(lastClose);
        setPriceChangePercent(0);
      }
    } catch (e) {
      showNotification(e.message || 'Lỗi tải dữ liệu biểu đồ.', 'error');
    } finally {
      setIsChartLoading(false);
    }
  };

  const handleSaveApiKey = () => {
    localStorage.setItem('gemini_api_key', keyInputTemp);
    setApiKey(keyInputTemp);
    setShowKeyInput(false);
    showNotification('Đã cập nhật Gemini API Key!');
  };

  const showNotification = (msg, severity = 'info') => {
    setTradingNotification({ msg, severity });
    setTimeout(() => setTradingNotification(null), 4000);
  };

  const handleRunAiAnalysis = async () => {
    if (!apiKey) {
      setShowKeyInput(true);
      showNotification('Vui lòng nhập Gemini API Key ở thanh điều khiển phía trên để tiếp tục.', 'error');
      return;
    }
    setIsAnalyzing(true);
    try {
      const res = await fetch(`${API_BASE}/ai/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: selectedStock.symbol, apiKey })
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setAiAnalysis(data);
      showNotification(`AI đã phân tích xong cổ phiếu ${selectedStock.symbol}!`);
    } catch (e) {
      console.error('AI Analysis failed:', e);
      showNotification(`Lỗi khi gọi AI phân tích: ${e.message}`, 'error');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleSendMessage = async (text) => {
    const userMsg = { role: 'user', text };
    setChatMessages(prev => [...prev, userMsg]);
    setIsChatting(true);

    try {
      const res = await fetch(`${API_BASE}/ai/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: selectedStock.symbol, message: text, apiKey })
      });
      const data = await res.json();
      setChatMessages(prev => [...prev, { role: 'ai', text: data.answer }]);
    } catch (e) {
      setChatMessages(prev => [...prev, { role: 'ai', text: 'Xin lỗi, tôi gặp lỗi kết nối với máy chủ AI.' }]);
    } finally {
      setIsChatting(false);
    }
  };

  // Tính cổ phiếu khả dụng (đã qua T+ lock) cho 1 holding.
  const availableSharesOf = (holding, now = Date.now()) => {
    if (!holding?.lots) return holding?.shares || 0;
    return holding.lots.filter(l => (now - l.buyAt) >= T_PLUS_LOCK_MS).reduce((s, l) => s + l.shares, 0);
  };
  const lockedSharesOf = (holding, now = Date.now()) => (holding?.shares || 0) - availableSharesOf(holding, now);

  // NAV tổng (tiền + giá thị trường * shares)
  const computeNav = (port) =>
    port.cash + port.holdings.reduce((sum, h) => sum + h.shares * h.currentPrice, 0);

  const executeBuyOrder = async (symbol, shares, isAi = false) => {
    const cost = shares * realtimePrice;
    if (cost > portfolio.cash) {
      if (!isAi) showNotification('Số dư khả dụng không đủ để thực hiện lệnh mua này!', 'error');
      return false;
    }
    const nav = computeNav(portfolio);
    const currentPosValue = (portfolio.holdings.find(h => h.symbol === symbol)?.shares || 0) * realtimePrice;
    const newPosValue = currentPosValue + cost;
    const maxAllowed = (nav * riskConfig.maxPositionPercent) / 100;
    if (newPosValue > maxAllowed) {
      const reason = `Vượt giới hạn position size: ${(newPosValue / nav * 100).toFixed(1)}% > ${riskConfig.maxPositionPercent}% NAV.`;
      if (!isAi) showNotification(reason, 'error');
      else console.log('[AI BOT] Bỏ qua lệnh mua —', reason);
      return false;
    }

    setIsTrading(true);
    try {
      const res = await fetch(`${API_BASE}/portfolio/buy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, shares, price: realtimePrice, executor: isAi ? 'AI' : 'USER' }),
      });
      const data = await res.json();
      if (!res.ok) {
        showNotification(`Lệnh mua thất bại: ${data.detail || res.status}`, 'error');
        return false;
      }
      setPortfolio(prev => mergePortfolioFromServer(data.portfolio, prev.holdings));
      setTransactionHistory(data.transactions || []);
      showNotification(`${isAi ? '[AI BOT] ' : ''}Khớp lệnh MUA ${shares} CP ${symbol} giá ${realtimePrice.toLocaleString()} đ (khóa T+2)`);
      return true;
    } catch (e) {
      showNotification(`Lỗi mạng khi đặt lệnh mua: ${e.message}`, 'error');
      return false;
    } finally {
      setIsTrading(false);
    }
  };

  const executeSellOrder = async (symbol, shares, isAi = false) => {
    const holding = portfolio.holdings.find(h => h.symbol === symbol);
    if (!holding) {
      if (!isAi) showNotification('Bạn không nắm giữ cổ phiếu này!', 'error');
      return false;
    }
    const avail = availableSharesOf(holding, Date.now());
    if (avail < shares) {
      const locked = holding.shares - avail;
      const reason = `Chỉ có ${avail} CP khả dụng — ${locked} CP đang bị khóa T+.`;
      if (!isAi) showNotification(reason, 'error');
      else console.log('[AI BOT] Bỏ qua lệnh bán —', reason);
      return false;
    }

    setIsTrading(true);
    try {
      const res = await fetch(`${API_BASE}/portfolio/sell`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, shares, price: realtimePrice, executor: isAi ? 'AI' : 'USER' }),
      });
      const data = await res.json();
      if (!res.ok) {
        showNotification(`Lệnh bán thất bại: ${data.detail || res.status}`, 'error');
        return false;
      }
      setPortfolio(prev => mergePortfolioFromServer(data.portfolio, prev.holdings));
      setTransactionHistory(data.transactions || []);
      showNotification(`${isAi ? '[AI BOT] ' : ''}Khớp lệnh BÁN ${shares} CP ${symbol} giá ${realtimePrice.toLocaleString()} đ`);
      return true;
    } catch (e) {
      showNotification(`Lỗi mạng khi đặt lệnh bán: ${e.message}`, 'error');
      return false;
    } finally {
      setIsTrading(false);
    }
  };

  const resetPortfolio = async () => {
    if (!window.confirm('Xác nhận reset portfolio về 100 triệu? Toàn bộ holdings và lịch sử sẽ xóa.')) return;
    try {
      const res = await fetch(`${API_BASE}/portfolio/reset`, { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setPortfolio({ cash: data.portfolio.cash, holdings: [] });
      setTransactionHistory([]);
      showNotification('Đã reset portfolio về 100 triệu.');
    } catch (e) {
      showNotification(`Reset thất bại: ${e.message}`, 'error');
    }
  };

  return (
    <div className="app-container">
      {/* Header */}
      <header className="glass-panel app-header">
        <div className="logo-section">
          <TrendingUp className="logo-icon" size={26} />
          <span className="logo-text">VN STOCK AI ANALYZER</span>
          <span className={`market-badge market-${marketStatus.status?.toLowerCase()}`}>
            <span className="market-dot" />
            {marketStatus.status === 'OPEN' ? 'Đang mở' : marketStatus.status === 'LUNCH' ? 'Nghỉ trưa' : 'Đóng cửa'}
            <span className="market-reason">— {marketStatus.reason}</span>
          </span>
        </div>

        {/* Global Live Ticker Info */}
        <div className="header-stats">
          <div className="stat-item">
            <span className="stat-label">Cổ phiếu đang xem</span>
            <span className="stat-value" style={{ fontWeight: '700', letterSpacing: '0.5px' }}>
              {selectedStock.symbol} ({selectedStock.exchange})
            </span>
          </div>
          <div className="stat-item">
            <span className="stat-label">Giá thị trường ({marketStatus.is_open ? 'Live · 5s' : 'Cached'})</span>
            <span className="stat-value font-display" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span className="pulse-indicator buy"></span>
              {realtimePrice > 0 ? realtimePrice.toLocaleString() : '---'} đ
            </span>
          </div>
          <div className="stat-item">
            <span className="stat-label">Biến động ngày</span>
            <span className={`stat-value font-display ${priceChangePercent >= 0 ? 'up' : 'down'}`}>
              {priceChangePercent >= 0 ? '+' : ''}{priceChangePercent.toFixed(2)}%
            </span>
          </div>
        </div>

        {/* Global actions */}
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <button 
            className={`btn btn-outline ${apiKey ? 'active-key' : ''}`} 
            onClick={() => {
              setKeyInputTemp(apiKey);
              setShowKeyInput(!showKeyInput);
            }}
            style={{ padding: '8px 14px', fontSize: '13px', display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <Key size={14} style={{ color: apiKey ? 'var(--color-buy)' : 'inherit' }} />
            <span>{apiKey ? 'Gemini API Connected' : 'Cấu hình API Key'}</span>
          </button>

          <button
            className="btn btn-outline"
            onClick={() => setShowScanner(true)}
            style={{ padding: '8px 14px', fontSize: '13px', display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <Radar size={14} />
            <span>AI Scanner</span>
          </button>

          <button
            className="btn btn-outline"
            onClick={() => setShowPortfolioReview(true)}
            style={{ padding: '8px 14px', fontSize: '13px', display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <Briefcase size={14} />
            <span>Review danh mục</span>
          </button>

          <button
            className="btn btn-outline"
            onClick={() => setShowBacktest(true)}
            style={{ padding: '8px 14px', fontSize: '13px', display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <Activity size={14} />
            <span>Backtest</span>
          </button>

          <button
            className={`btn ${isAutoTrading ? 'btn-sell glowing' : 'btn-outline'}`}
            onClick={() => {
              if (!apiKey) {
                showNotification('Vui lòng cấu hình Gemini API Key trước khi kích hoạt Auto-Trading!', 'error');
                setShowKeyInput(true);
                return;
              }
              setIsAutoTrading(!isAutoTrading);
              showNotification(isAutoTrading ? 'Đã tắt Bot tự động giao dịch' : 'Đã bật Bot tự động giao dịch AI!');
            }}
            style={{ padding: '8px 14px', fontSize: '13px', display: 'flex', alignItems: 'center', gap: 6 }}
          >
            {isAutoTrading ? <Square size={12} /> : <Play size={12} />}
            <span>{isAutoTrading ? 'Dừng AI Auto-Bot' : 'Kích hoạt AI Auto-Bot'}</span>
          </button>
        </div>
      </header>

      {/* Floating Key Configuration Dialog */}
      {showKeyInput && (
        <div className="glass-panel api-key-popup">
          <div className="popup-title">Nhập Gemini API Key</div>
          <p className="popup-desc">Key này dùng để gọi Gemini phân tích dữ liệu trực tiếp trên thiết bị của bạn.</p>
          <div style={{ display: 'flex', gap: 8 }}>
            <input 
              type="password"
              placeholder="AIzaSy..." 
              value={keyInputTemp}
              onChange={(e) => setKeyInputTemp(e.target.value)}
              className="key-input"
            />
            <button className="btn btn-primary" onClick={handleSaveApiKey}>Lưu</button>
            <button className="btn btn-outline" onClick={() => setShowKeyInput(false)}>Hủy</button>
          </div>
        </div>
      )}

      {/* Global Notifications popup */}
      {tradingNotification && (
        <div className={`notification-banner notification-${tradingNotification.severity || 'info'}`}>
          <Bell size={16} />
          <span>{tradingNotification.msg}</span>
        </div>
      )}

      {/* Dashboard Body */}
      <main className="dashboard-grid">
        
        {/* Column 1: Search, Watchlist, & Manual Trading Panel */}
        <section className="column">
          {/* Market overview - foreign trade + sector heatmap */}
          <MarketPanel apiBase={API_BASE} />

          {/* Search Box */}
          <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column' }}>
            <div className="panel-header">
              <div className="panel-title">
                <Search size={16} className="text-accent" />
                <span>Tìm kiếm & Watchlist</span>
              </div>
            </div>
            <div className="panel-content" style={{ gap: 10 }}>
              <div className="search-input-wrapper">
                <input 
                  type="text" 
                  placeholder="Nhập mã cổ phiếu VN (ví dụ: FPT, HPG, SSI)..." 
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>
              
              {/* Search dropdown results */}
              {searchQuery && searchResults.length > 0 && (
                <div className="search-results-dropdown">
                  {searchResults.map((stock, i) => (
                    <div 
                      className="search-result-row"
                      key={i} 
                      onClick={() => {
                        setSelectedStock(stock);
                        setSearchQuery('');
                      }}
                    >
                      <span className="ticker font-display">{stock.symbol}</span>
                      <span className="name">{stock.name}</span>
                      <span className="exchange">{stock.exchange}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Default Watchlist */}
              <div className="watchlist-wrapper">
                <div className="sub-label">Cổ phiếu Phổ biến VN</div>
                <div className="watchlist-list">
                  {[
                    { symbol: 'FPT', name: 'FPT Corp', exchange: 'HOSE' },
                    { symbol: 'HPG', name: 'Tập đoàn Hòa Phát', exchange: 'HOSE' },
                    { symbol: 'TCB', name: 'Techcombank', exchange: 'HOSE' },
                    { symbol: 'VNM', name: 'Vinamilk', exchange: 'HOSE' },
                    { symbol: 'SSI', name: 'Chứng khoán SSI', exchange: 'HOSE' },
                    { symbol: 'VND', name: 'Chứng khoán VNDIRECT', exchange: 'HOSE' }
                  ].map((stock, i) => (
                    <div 
                      key={i} 
                      className={`watchlist-item ${selectedStock.symbol === stock.symbol ? 'active' : ''}`}
                      onClick={() => setSelectedStock(stock)}
                    >
                      <span className="item-symbol font-display">{stock.symbol}</span>
                      <span className="item-name">{stock.name}</span>
                      <span className="item-exchange">{stock.exchange}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Quick Manual Trade Board */}
          <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column' }}>
            <div className="panel-header">
              <div className="panel-title">
                <BarChart2 size={16} className="text-accent" />
                <span>Đặt lệnh thủ công</span>
              </div>
            </div>
            <div className="panel-content" style={{ gap: 14 }}>
              <div className="trading-fields">
                <div className="field-group">
                  <label>Mã giao dịch</label>
                  <input type="text" value={selectedStock.symbol} disabled />
                </div>
                <div className="field-group">
                  <label>Số lượng</label>
                  <input 
                    type="number" 
                    min="1" 
                    value={tradeShares} 
                    onChange={(e) => setTradeShares(Math.max(1, parseInt(e.target.value) || 1))} 
                  />
                </div>
              </div>
              <div className="trading-stats-row">
                <span>Tổng giá trị lệnh:</span>
                <span className="font-display font-bold">
                  {(tradeShares * realtimePrice).toLocaleString()} đ
                </span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <button className="btn btn-buy" onClick={() => executeBuyOrder(selectedStock.symbol, tradeShares)} disabled={isTrading}>
                  {isTrading ? '...' : 'MUA VÀO'}
                </button>
                <button className="btn btn-sell" onClick={() => executeSellOrder(selectedStock.symbol, tradeShares)} disabled={isTrading}>
                  {isTrading ? '...' : 'BÁN RA'}
                </button>
              </div>
              <button
                className="btn btn-outline"
                onClick={resetPortfolio}
                style={{ padding: '6px', fontSize: '11px', marginTop: '4px' }}
              >
                Reset portfolio về 100tr
              </button>
            </div>
          </div>

          {/* Fundamentals Panel */}
          <Fundamentals data={fundamentals} symbol={selectedStock.symbol} />

          {/* News Panel */}
          <News items={newsItems} symbol={selectedStock.symbol} apiBase={API_BASE} apiKey={apiKey} />

          {/* Risk Config Panel */}
          <div className="glass-panel">
            <div className="panel-header">
              <div className="panel-title">
                <Shield size={16} className="text-accent" />
                <span>Quản trị rủi ro (AI Bot)</span>
              </div>
              {botPaused ? <span className="bot-paused">Bot đang tạm dừng</span> : null}
            </div>
            <div className="panel-content risk-grid">
              <div className="risk-field">
                <label>Max 1 mã (% NAV)</label>
                <input
                  type="number" min="5" max="100"
                  value={riskConfig.maxPositionPercent}
                  onChange={(e) => setRiskConfig(c => ({ ...c, maxPositionPercent: Math.max(5, Math.min(100, Number(e.target.value) || 20)) }))}
                />
              </div>
              <div className="risk-field">
                <label>Daily loss limit (%)</label>
                <input
                  type="number" min="1" max="20"
                  value={riskConfig.dailyLossLimitPercent}
                  onChange={(e) => setRiskConfig(c => ({ ...c, dailyLossLimitPercent: Math.max(1, Math.min(20, Number(e.target.value) || 3)) }))}
                />
              </div>
              <div className="risk-field">
                <label>Cash mỗi lệnh (%)</label>
                <input
                  type="number" min="5" max="100"
                  value={riskConfig.botCashUsagePercent}
                  onChange={(e) => setRiskConfig(c => ({ ...c, botCashUsagePercent: Math.max(5, Math.min(100, Number(e.target.value) || 20)) }))}
                />
              </div>
              {botPaused ? (
                <button className="btn btn-primary risk-resume" onClick={() => {
                  sessionStartNavRef.current = computeNav(portfolio);
                  setBotPaused(false);
                  showNotification('Đã reset NAV mốc và tiếp tục bot.');
                }}>Reset & tiếp tục</button>
              ) : null}
            </div>
          </div>

          {/* Lịch sự kiện 30 ngày — chỉ filter portfolio + watchlist */}
          <CalendarPanel
            apiBase={API_BASE}
            watchlistSymbols={[
              ...new Set([
                ...portfolio.holdings.map(h => h.symbol),
                'FPT', 'HPG', 'TCB', 'VNM', 'SSI', 'VND',
              ]),
            ]}
          />

          {/* Alerts engine */}
          <AlertsManager apiBase={API_BASE} />
        </section>

        {/* Column 2: Main Chart & Portfolio */}
        <section className="main-column">
          {/* Stock Chart Panel */}
          <div className="glass-panel" style={{ flexGrow: 1, minHeight: '400px', display: 'flex', flexDirection: 'column' }}>
            <div className="panel-header">
              <div className="panel-title">
                <Compass size={18} className="logo-icon" />
                <span>Biểu đồ kỹ thuật: {selectedStock.symbol} - {selectedStock.name}</span>
              </div>
              {isChartLoading && (
                <div className="loading-indicator">
                  <RefreshCw className="spin-icon" size={14} />
                  <span>Đang tải...</span>
                </div>
              )}
            </div>
            <div className="panel-content" style={{ padding: '8px', justifyContent: 'center' }}>
              {!isChartLoading && chartData.length > 0 ? (
                <StockChart data={chartData} symbol={selectedStock.symbol} />
              ) : (
                <div style={{ color: 'var(--text-muted)', textAlign: 'center', fontSize: '13px' }}>
                  {isChartLoading ? 'Đang chuẩn bị dữ liệu...' : 'Không có dữ liệu biểu đồ.'}
                </div>
              )}
            </div>
          </div>

          {/* Portfolio & History Tracker Panel */}
          <PortfolioTracker
            portfolio={portfolio}
            transactionHistory={transactionHistory}
            nowTick={nowTick}
            onSellHolding={(symbol) => {
              const holding = portfolio.holdings.find(h => h.symbol === symbol);
              if (!holding) return;
              const sellable = availableSharesOf(holding);
              if (sellable > 0) executeSellOrder(symbol, sellable);
            }}
          />
        </section>

        {/* Column 3: AI Analyst Panel + Insider deals */}
        <section className="column">
          <AiAnalyst
            analysisData={aiAnalysis}
            isAnalyzing={isAnalyzing}
            onRunAnalysis={handleRunAiAnalysis}
            chatMessages={chatMessages}
            onSendMessage={handleSendMessage}
            isChatting={isChatting}
          />

          {/* Giao dịch nội bộ cho mã đang xem */}
          <InsiderPanel apiBase={API_BASE} symbol={selectedStock.symbol} />
        </section>

      </main>

      <BacktestModal
        open={showBacktest}
        onClose={() => setShowBacktest(false)}
        defaultSymbol={selectedStock.symbol}
        apiBase={API_BASE}
      />

      {/* AI Scanner modal */}
      {showScanner && (
        <div className="scanner-backdrop" onClick={() => setShowScanner(false)}>
          <div className="scanner-modal glass-panel" onClick={(e) => e.stopPropagation()}>
            <div className="scanner-modal-header">
              <span>AI Scanner</span>
              <button className="scanner-modal-close" onClick={() => setShowScanner(false)}>×</button>
            </div>
            <AIScanner
              apiBase={API_BASE}
              apiKey={apiKey}
              onSelectSymbol={(sym) => {
                setSelectedStock({ symbol: sym, name: sym, exchange: 'HOSE' });
                setShowScanner(false);
              }}
            />
          </div>
        </div>
      )}

      {/* Portfolio Review modal */}
      <PortfolioReview
        open={showPortfolioReview}
        onClose={() => setShowPortfolioReview(false)}
        apiBase={API_BASE}
        apiKey={apiKey}
      />

      {/* Embedded page styles */}
      <style>{`
        /* Popup */
        .api-key-popup {
          position: absolute;
          top: 80px;
          right: 32px;
          z-index: 100;
          width: 320px;
          padding: 16px;
          border-color: var(--color-accent);
          background: rgba(4, 8, 21, 0.95);
        }
        .popup-title {
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 14px;
          margin-bottom: 6px;
        }
        .popup-desc {
          font-size: 11px;
          color: var(--text-secondary);
          margin-bottom: 12px;
          line-height: 1.4;
        }
        .key-input {
          flex-grow: 1;
          background: rgba(0, 0, 0, 0.3);
          border: 1px solid var(--border-color);
          border-radius: 6px;
          padding: 8px 10px;
          color: #fff;
          font-size: 12px;
        }
        .key-input:focus {
          outline: none;
          border-color: var(--color-accent);
        }

        /* Notification banner */
        .notification-banner {
          position: fixed;
          bottom: 24px;
          right: 24px;
          backdrop-filter: blur(12px);
          padding: 12px 20px;
          border-radius: 10px;
          z-index: 1000;
          display: flex;
          align-items: center;
          gap: 10px;
          font-size: 12px;
          box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
          animation: slide-up-in 0.3s ease-out;
        }
        .notification-info {
          background: rgba(6, 182, 212, 0.15);
          border: 1px solid var(--color-accent);
          color: #e2f8ff;
        }
        .notification-error {
          background: rgba(244, 63, 94, 0.18);
          border: 1px solid #f43f5e;
          color: #ffe4ea;
        }
        @keyframes slide-up-in {
          from { transform: translateY(100px); opacity: 0; }
          to { transform: translateY(0); opacity: 1; }
        }

        /* Search input */
        .search-input-wrapper {
          position: relative;
        }
        .search-input-wrapper input {
          width: 100%;
          background: rgba(0, 0, 0, 0.3);
          border: 1px solid var(--border-color);
          border-radius: 8px;
          padding: 10px 12px;
          color: #fff;
          font-size: 12px;
          font-family: var(--font-main);
        }
        .search-input-wrapper input:focus {
          outline: none;
          border-color: var(--color-accent);
          box-shadow: 0 0 10px rgba(6, 182, 212, 0.1);
        }

        /* Search Dropdown */
        .search-results-dropdown {
          background: rgba(10, 17, 40, 0.95);
          border: 1px solid var(--border-color);
          border-radius: 8px;
          max-height: 200px;
          overflow-y: auto;
          position: absolute;
          z-index: 50;
          width: calc(100% - 40px);
          box-shadow: var(--shadow-glass);
          margin-top: 42px;
        }
        .search-result-row {
          padding: 10px 12px;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 10px;
          border-bottom: 1px solid rgba(255, 255, 255, 0.02);
          font-size: 11px;
        }
        .search-result-row:hover {
          background: rgba(255, 255, 255, 0.04);
        }
        .search-result-row .ticker {
          font-weight: 700;
          color: var(--color-accent);
          width: 50px;
        }
        .search-result-row .name {
          flex-grow: 1;
          color: var(--text-secondary);
        }
        .search-result-row .exchange {
          font-size: 10px;
          color: var(--text-muted);
        }

        /* Watchlist */
        .watchlist-wrapper {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .sub-label {
          font-size: 10px;
          color: var(--text-muted);
          text-transform: uppercase;
          letter-spacing: 0.5px;
          margin-bottom: 2px;
        }
        .watchlist-list {
          display: flex;
          flex-direction: column;
          gap: 6px;
          max-height: 180px;
          overflow-y: auto;
        }
        .watchlist-item {
          display: flex;
          align-items: center;
          padding: 8px 12px;
          border-radius: 6px;
          background: rgba(255, 255, 255, 0.01);
          border: 1px solid transparent;
          cursor: pointer;
          font-size: 11px;
          transition: all 0.2s;
        }
        .watchlist-item:hover {
          background: rgba(255, 255, 255, 0.03);
          border-color: rgba(255, 255, 255, 0.05);
        }
        .watchlist-item.active {
          background: rgba(6, 182, 212, 0.06);
          border-color: rgba(6, 182, 212, 0.2);
        }
        .item-symbol {
          font-weight: 700;
          color: #fff;
          width: 50px;
        }
        .item-name {
          flex-grow: 1;
          color: var(--text-secondary);
          text-align: left;
        }
        .item-exchange {
          font-size: 9px;
          color: var(--text-muted);
        }

        /* Manual Trading Board */
        .trading-fields {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 12px;
        }
        .field-group {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .field-group label {
          font-size: 10px;
          color: var(--text-muted);
          text-transform: uppercase;
        }
        .field-group input {
          background: rgba(0, 0, 0, 0.3);
          border: 1px solid var(--border-color);
          border-radius: 6px;
          padding: 8px 10px;
          color: #fff;
          font-size: 12px;
          font-family: var(--font-main);
          width: 100%;
        }
        .field-group input:focus {
          outline: none;
          border-color: var(--color-accent);
        }
        .field-group input:disabled {
          color: var(--text-secondary);
          opacity: 0.6;
        }
        .trading-stats-row {
          display: flex;
          justify-content: space-between;
          font-size: 12px;
          padding: 8px 0;
          border-top: 1px dashed var(--border-color);
        }
        .font-bold {
          font-weight: 700;
        }

        /* AI Scanner modal wrapper */
        .scanner-backdrop {
          position: fixed; inset: 0; z-index: 200;
          background: rgba(2, 6, 23, 0.7);
          backdrop-filter: blur(4px);
          display: flex; align-items: center; justify-content: center;
          animation: fade-in 0.2s ease-out;
        }
        .scanner-modal {
          width: min(1000px, 94vw);
          max-height: 92vh;
          padding: 18px 22px;
          display: flex; flex-direction: column;
          overflow-y: auto;
        }
        .scanner-modal-header {
          display: flex; align-items: center; justify-content: space-between;
          margin-bottom: 12px;
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 16px;
        }
        .scanner-modal-close {
          background: transparent; border: none; color: var(--text-muted);
          cursor: pointer; font-size: 24px; line-height: 1;
          padding: 0 8px;
        }
        .scanner-modal-close:hover { color: var(--text-primary); }

        /* Risk Config */
        .risk-grid {
          display: grid;
          grid-template-columns: 1fr 1fr 1fr;
          gap: 10px;
        }
        .risk-field {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .risk-field label {
          font-size: 9px;
          color: var(--text-muted);
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .risk-field input {
          background: rgba(0, 0, 0, 0.3);
          border: 1px solid var(--border-color);
          border-radius: 6px;
          padding: 6px 8px;
          color: #fff;
          font-size: 12px;
          font-family: var(--font-display);
        }
        .risk-field input:focus {
          outline: none;
          border-color: var(--color-accent);
        }
        .risk-resume {
          grid-column: 1 / -1;
          padding: 8px;
          font-size: 11px;
        }
        .bot-paused {
          font-size: 10px;
          padding: 2px 8px;
          border-radius: 999px;
          background: rgba(244, 63, 94, 0.15);
          color: #fda4af;
          border: 1px solid rgba(244, 63, 94, 0.3);
        }

        /* Market status badge */
        .market-badge {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          margin-left: 14px;
          padding: 4px 10px;
          border-radius: 999px;
          font-size: 11px;
          font-weight: 600;
          letter-spacing: 0.3px;
          border: 1px solid transparent;
        }
        .market-badge .market-dot {
          width: 7px;
          height: 7px;
          border-radius: 50%;
          display: inline-block;
        }
        .market-badge .market-reason {
          font-weight: 400;
          opacity: 0.75;
          font-size: 10px;
        }
        .market-open {
          background: rgba(16, 185, 129, 0.12);
          border-color: rgba(16, 185, 129, 0.35);
          color: var(--color-buy);
        }
        .market-open .market-dot {
          background: var(--color-buy);
          box-shadow: 0 0 8px var(--color-buy);
          animation: pulse-dot 1.6s infinite;
        }
        .market-lunch {
          background: rgba(234, 179, 8, 0.12);
          border-color: rgba(234, 179, 8, 0.35);
          color: #facc15;
        }
        .market-lunch .market-dot { background: #facc15; }
        .market-closed {
          background: rgba(148, 163, 184, 0.1);
          border-color: rgba(148, 163, 184, 0.3);
          color: var(--text-secondary);
        }
        .market-closed .market-dot { background: var(--text-muted); }
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }

        /* Chart Header Load Indicator */
        .loading-indicator {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 11px;
          color: var(--color-accent);
        }
        .spin-icon {
          animation: spin 1.5s linear infinite;
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
