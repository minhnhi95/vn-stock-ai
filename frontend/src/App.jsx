import { lazy, Suspense, useCallback, useState, useEffect } from 'react';
import { Search, TrendingUp, Key, Bell, Compass, RefreshCw, Globe2 } from 'lucide-react';

// Components
import StockChart from './components/StockChart';
import AiAnalyst from './components/AiAnalyst';
import RealPortfolio from './components/RealPortfolio';
import Fundamentals from './components/Fundamentals';
import News from './components/News';
import ErrorBoundary from './components/ErrorBoundary';
import useModalDismiss from './hooks/useModalDismiss';

import MarketPanel from './components/MarketPanel';
import DailyBrief from './components/DailyBrief';
import VerdictCard from './components/VerdictCard';
import TradePlan from './components/TradePlan';
import PersonalFinance from './components/PersonalFinance';
import VerdictScan from './components/VerdictScan';
const SafetyScreenModal = lazy(() => import('./components/SafetyScreenModal'));
const MarketFinder = lazy(() => import('./components/MarketFinder'));
import AlertsManager from './components/AlertsManager';
import CalendarPanel from './components/CalendarPanel';
import InsiderPanel from './components/InsiderPanel';
const PortfolioReview = lazy(() => import('./components/PortfolioReview'));
import { ShieldCheck, Briefcase } from 'lucide-react';

// API endpoint. Production đặt VITE_API_BASE qua Vercel env. Chạy local mà không
// đặt thì gọi về CHÍNH máy đang phục vụ trang, cổng 8765: mở bằng localhost thì gọi
// localhost, mở từ điện thoại qua IP Wi-Fi thì gọi đúng IP đó. Bản cũ ghim cứng một
// IP trong .env.local, nên mỗi lần hotspot cấp IP khác là mọi panel treo "Đang tải".
// Bỏ trailing slash để không gây double-slash khi nối path.
function resolveApiBase() {
  const fromEnv = import.meta.env.VITE_API_BASE;
  if (fromEnv) return fromEnv.replace(/\/$/, '');
  const { protocol, hostname } = window.location;
  return `${protocol}//${hostname}:8765`;
}
const RAW_BASE = resolveApiBase();
const API_BASE = `${RAW_BASE}/api`;

// 4 tab mobile. Thứ tự theo việc người dùng làm nhiều nhất: xem mã -> xem thị
// trường -> xem danh mục -> kiểm tra theo dõi.
const MOBILE_TABS = [
  { id: 'stock', label: 'Cổ phiếu', Icon: Compass },
  { id: 'market', label: 'Thị trường', Icon: Globe2 },
  { id: 'portfolio', label: 'Danh mục', Icon: Briefcase },
  { id: 'watch', label: 'Theo dõi', Icon: Bell },
];

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
  // Backend trả is_intraday=false khi ngoài giờ khớp lệnh (giá = đóng cửa phiên gần nhất).
  const [priceMeta, setPriceMeta] = useState({ isIntraday: null, time: '', source: '' });
  const [originalLastClose, setOriginalLastClose] = useState(0);
  const [priceChangePercent, setPriceChangePercent] = useState(0);

  // AI State
  const [aiAnalysis, setAiAnalysis] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [chatMessages, setChatMessages] = useState([]);
  const [isChatting, setIsChatting] = useState(false);

  // Market status & fundamentals & news
  const [marketStatus, setMarketStatus] = useState({ status: 'CLOSED', reason: '...', is_open: false });
  const [fundamentals, setFundamentals] = useState(null);
  const [newsItems, setNewsItems] = useState([]);

  // Tab đang xem trên mobile. Desktop bỏ qua state này (CSS hiện tất cả).
  const [mobileTab, setMobileTab] = useState('stock');

  // Thông báo ngắn (lỗi tải dữ liệu, cập nhật API key).
  const [toast, setToast] = useState(null);

  const [showSafetyScreen, setShowSafetyScreen] = useState(false);
  const [showFinder, setShowFinder] = useState(false);
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

  // Poll market status mỗi 30s — chỉ điều phối, không tốn tài nguyên.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const res = await fetch(`${API_BASE}/market/status`);
        const data = await res.json();
        if (!cancelled) setMarketStatus(data);
      } catch {
        // im lặng — không phá flow chính
      }
    };
    tick();
    const id = setInterval(tick, 30000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // Modal lọc an toàn dựng inline ở đây (không phải component riêng) nên gắn
  // Escape-to-close tại App. Hai modal còn lại tự gọi hook trong file của chúng.
  // Chọn mã từ bất kỳ panel nào. Trên điện thoại phải nhảy sang tab "Cổ phiếu": bấm
  // một mã ở tab Thị trường mà màn hình không đổi gì thì người dùng tưởng nút hỏng.
  const openStock = useCallback((symbol, name) => {
    setSelectedStock({ symbol, name: name || symbol });
    setMobileTab('stock');
  }, []);

  const closeSafetyScreen = useCallback(() => setShowSafetyScreen(false), []);
  const closeFinder = useCallback(() => setShowFinder(false), []);
  useModalDismiss(showSafetyScreen, closeSafetyScreen);

  // Tiêu đề tab bám theo mã + giá — người dùng thường mở nhiều tab cho nhiều mã,
  // và biết giá mà không cần chuyển tab là thứ app chứng khoán nào cũng có.
  useEffect(() => {
    const sym = selectedStock?.symbol;
    if (!sym) return;
    const price = realtimePrice > 0 ? realtimePrice.toLocaleString() : null;
    const arrow = priceChangePercent > 0 ? '▲' : priceChangePercent < 0 ? '▼' : '';
    document.title = price
      ? `${sym} ${price} ${arrow}${priceChangePercent.toFixed(2)}% · VN Stock AI`
      : `${sym} · VN Stock AI`;
  }, [selectedStock, realtimePrice, priceChangePercent]);

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
    // Chờ nến lịch sử tải xong rồi mới poll giá. loadStockData đặt originalLastClose
    // cùng lúc với realtimePrice, và originalLastClose có trong danh sách phụ thuộc —
    // điều kiện dựa trên một state không khai báo phụ thuộc là đọc phải giá trị cũ.
    if (!selectedStock?.symbol || originalLastClose <= 0) return;
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
    };

    const fetchPrice = async () => {
      try {
        const res = await fetch(`${API_BASE}/stocks/realtime?symbol=${encodeURIComponent(selectedStock.symbol)}`);
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled) return;
        if (data?.price) {
          applyPrice(Number(data.price));
          setPriceMeta({
            isIntraday: data.is_intraday !== false,
            time: data.time || '',
            source: data.source || '',
          });
        }
      } catch {
        // im lặng — poll kế tiếp sẽ thử lại
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
      } catch {
        // im lặng
      }
    })();
    return () => { cancelled = true; };
  }, [selectedStock]);

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
    setToast({ msg, severity });
    setTimeout(() => setToast(null), 4000);
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
    } catch {
      setChatMessages(prev => [...prev, { role: 'ai', text: 'Xin lỗi, tôi gặp lỗi kết nối với máy chủ AI.' }]);
    } finally {
      setIsChatting(false);
    }
  };

  // Tính cổ phiếu khả dụng (đã qua T+ lock) cho 1 holding.
  const priceSourceLabel = (() => {
    if (priceMeta.isIntraday === false) {
      const day = String(priceMeta.time || '').split(' ')[0];
      return day ? `Đóng cửa ${day}` : 'Đóng cửa phiên trước';
    }
    return marketStatus.is_open ? 'Khớp lệnh · 5s' : 'Khớp lệnh gần nhất';
  })();

  return (
    <div className="app-container">
      {/* Header */}
      <header className="glass-panel app-header">
        <div className="logo-section">
          <TrendingUp className="logo-icon" size={24} />
          <span className="logo-text">VN STOCK AI</span>
        </div>

        {/* Global Live Ticker Info */}
        <div className="header-stats">
          <span className={`market-badge market-${marketStatus.status?.toLowerCase()}`}>
            <span className="market-dot" />
            {marketStatus.status === 'OPEN' ? 'Đang mở' : marketStatus.status === 'LUNCH' ? 'Nghỉ trưa' : 'Đóng cửa'}
            <span className="market-reason">— {marketStatus.reason}</span>
          </span>
          <div className="stat-item">
            <span className="stat-label">Cổ phiếu đang xem</span>
            <span className="stat-value" style={{ fontWeight: '700', letterSpacing: '0.5px' }}>
              {selectedStock.symbol}
              {selectedStock.sector || selectedStock.exchange
                ? ` (${selectedStock.sector || selectedStock.exchange})`
                : ''}
            </span>
          </div>
          <div className="stat-item">
            <span className="stat-label">Giá thị trường ({priceSourceLabel})</span>
            <span className="stat-value font-display" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span className={`pulse-indicator ${priceMeta.isIntraday === false ? '' : 'buy'}`}></span>
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
        <div className="header-actions">
          <button 
            className={`btn btn-outline header-btn ${apiKey ? 'active-key' : ''}`}
            onClick={() => {
              setKeyInputTemp(apiKey);
              setShowKeyInput(!showKeyInput);
            }}
            title={apiKey ? 'Gemini API đã kết nối' : 'Cấu hình API Key'}
          >
            <Key size={14} style={{ color: apiKey ? 'var(--color-buy)' : 'inherit' }} />
            <span className="header-btn-label">{apiKey ? 'API Key' : 'API Key'}</span>
          </button>

          <button
            className="btn btn-outline header-btn"
            onClick={() => setShowFinder(true)}
            title="Tìm mã đáng mua toàn thị trường"
          >
            <Search size={14} />
            <span className="header-btn-label">Tìm mã</span>
          </button>

          <button
            className="btn btn-outline header-btn"
            onClick={() => setShowSafetyScreen(true)}
            title="Kiểm tra an toàn nhiều mã"
          >
            <ShieldCheck size={14} />
            <span className="header-btn-label">Lọc an toàn</span>
          </button>

          <button
            className="btn btn-outline header-btn"
            onClick={() => setShowPortfolioReview(true)}
            title="Đánh giá rủi ro danh mục"
          >
            <Briefcase size={14} />
            <span className="header-btn-label">Danh mục</span>
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
      {toast && (
        <div className={`notification-banner notification-${toast.severity || 'info'}`}>
          <Bell size={16} />
          <span>{toast.msg}</span>
        </div>
      )}

      {/* Dashboard Body */}
      <main className={`dashboard-grid mobile-tab-${mobileTab}`}>
        
        {/* Column 1: Search, Watchlist, & Manual Trading Panel */}
        <section className="column">
          <div className="panel-slot" data-tab="market">
            <ErrorBoundary name="Kết luận cả rổ">
              <VerdictScan
                onOpenFinder={() => setShowFinder(true)}
                apiBase={API_BASE}
                onSelectSymbol={openStock}
              />
            </ErrorBoundary>
          </div>

          <div className="panel-slot" data-tab="market">
  <ErrorBoundary name="Bản tin sáng nay">
              <DailyBrief
                apiBase={API_BASE}
                onSelectSymbol={openStock}
              />
            </ErrorBoundary>
          </div>

          <div className="panel-slot" data-tab="market">
  {/* Market overview - foreign trade + sector heatmap */}
            <ErrorBoundary name="Toàn cảnh thị trường">
              <MarketPanel apiBase={API_BASE} />
            </ErrorBoundary>
          </div>

          <div className="panel-slot" data-tab="stock">
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
                    placeholder="Tìm mã, tên công ty hoặc ngành (FPT, Hòa Phát, ngân hàng)..." 
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
                          openStock(stock.symbol, stock.name);
                          setSearchQuery('');
                        }}
                      >
                        <span className="ticker font-display">{stock.symbol}</span>
                        <span className="name">{stock.name}</span>
                        <span className="exchange">{stock.sector || stock.exchange || ''}</span>
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
                        onClick={() => openStock(stock.symbol, stock.name)}
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
          </div>

          <div className="panel-slot" data-tab="stock">
            <ErrorBoundary name="Kết luận">
              <VerdictCard apiBase={API_BASE} symbol={selectedStock.symbol} />
            </ErrorBoundary>
          </div>

          <div className="panel-slot" data-tab="stock">
            <ErrorBoundary name="Kế hoạch vào lệnh">
              <TradePlan apiBase={API_BASE} symbol={selectedStock.symbol} />
            </ErrorBoundary>
          </div>

          <div className="panel-slot" data-tab="stock">
  {/* Fundamentals Panel */}
            <ErrorBoundary name="Cơ bản doanh nghiệp">
              <Fundamentals data={fundamentals} symbol={selectedStock.symbol} />
            </ErrorBoundary>
          </div>

          <div className="panel-slot" data-tab="stock">
  {/* News Panel */}
            <ErrorBoundary name="Tin tức">
              <News items={newsItems} symbol={selectedStock.symbol} apiBase={API_BASE} apiKey={apiKey} />
            </ErrorBoundary>
          </div>

          <div className="panel-slot" data-tab="watch">
  <CalendarPanel
              apiBase={API_BASE}
              watchlistSymbols={[
                ...new Set([selectedStock.symbol, 'FPT', 'HPG', 'TCB', 'VNM', 'SSI', 'VND']),
              ]}
            />
          </div>

          <div className="panel-slot" data-tab="watch">
  {/* Alerts engine */}
            <ErrorBoundary name="Cảnh báo">
              <AlertsManager apiBase={API_BASE} marketOpen={marketStatus.is_open} />
            </ErrorBoundary>
          </div>
        </section>

        {/* Column 2: Main Chart & Portfolio */}
        <section className="main-column">
          <div className="panel-slot" data-tab="stock">
  {/* Stock Chart Panel */}
            <div className="glass-panel chart-panel">
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
              <div className="panel-content chart-panel-content">
                {!isChartLoading && chartData.length > 0 ? (
                  <ErrorBoundary name="Biểu đồ kỹ thuật">
                    <StockChart data={chartData} symbol={selectedStock.symbol} />
                  </ErrorBoundary>
                ) : (
                  <div style={{ color: 'var(--text-muted)', textAlign: 'center', fontSize: '13px' }}>
                    {isChartLoading ? 'Đang chuẩn bị dữ liệu...' : 'Không có dữ liệu biểu đồ.'}
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="panel-slot" data-tab="portfolio">
            <ErrorBoundary name="Tài chính cá nhân">
              <PersonalFinance apiBase={API_BASE} />
            </ErrorBoundary>
          </div>

          <div className="panel-slot" data-tab="portfolio">
  <ErrorBoundary name="Danh mục thật">
              <RealPortfolio apiBase={API_BASE} />
            </ErrorBoundary>
          </div>

        </section>

        {/* Column 3: AI Analyst Panel + Insider deals */}
        <section className="column">
          <div className="panel-slot" data-tab="stock">
  <AiAnalyst
              analysisData={aiAnalysis}
              isAnalyzing={isAnalyzing}
              onRunAnalysis={handleRunAiAnalysis}
              chatMessages={chatMessages}
              onSendMessage={handleSendMessage}
              isChatting={isChatting}
            />
          </div>

          <div className="panel-slot" data-tab="stock">
  {/* Giao dịch nội bộ cho mã đang xem */}
            <ErrorBoundary name="Giao dịch nội bộ">
              <InsiderPanel apiBase={API_BASE} symbol={selectedStock.symbol} />
            </ErrorBoundary>
          </div>
        </section>

      </main>

      <nav className="mobile-nav" aria-label="Điều hướng">
        {MOBILE_TABS.map((tab) => {
          const Icon = tab.Icon;
          return (
            <button
              key={tab.id}
              type="button"
              className={`mobile-nav-btn ${mobileTab === tab.id ? 'active' : ''}`}
              onClick={() => {
                setMobileTab(tab.id);
                window.scrollTo({ top: 0, behavior: 'smooth' });
              }}
              aria-current={mobileTab === tab.id ? 'page' : undefined}
            >
              <Icon size={18} />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </nav>

      <Suspense fallback={null}>
        {showSafetyScreen ? (
          <SafetyScreenModal
            apiBase={API_BASE}
            open={showSafetyScreen}
            onClose={closeSafetyScreen}
            onSelectSymbol={openStock}
          />
        ) : null}

        {showFinder ? (
          <MarketFinder
            apiBase={API_BASE}
            open={showFinder}
            onClose={closeFinder}
            onSelectSymbol={openStock}
          />
        ) : null}

        {/* Portfolio Review modal */}
        {showPortfolioReview ? (
          <PortfolioReview
            open={showPortfolioReview}
            onClose={() => setShowPortfolioReview(false)}
            apiBase={API_BASE}
            apiKey={apiKey}
          />
        ) : null}
      </Suspense>

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

        /* Modal lọc an toàn nhiều mã */
        .safety-modal-backdrop {
          position: fixed; inset: 0; z-index: 200;
          background: rgba(2, 6, 23, 0.7);
          backdrop-filter: blur(4px);
          display: flex; align-items: center; justify-content: center;
          animation: fade-in 0.2s ease-out;
        }
        .safety-modal {
          width: min(1000px, 94vw);
          max-height: 92vh;
          padding: 18px 22px;
          display: flex; flex-direction: column;
          overflow-y: auto;
        }
        .safety-modal-header {
          display: flex; align-items: center; justify-content: space-between;
          margin-bottom: 12px;
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 16px;
        }
        .safety-modal-close {
          background: transparent; border: none; color: var(--text-muted);
          cursor: pointer; font-size: 24px; line-height: 1;
          padding: 0 8px;
        }
        .safety-modal-close:hover { color: var(--text-primary); }

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
          /* Badge giờ nằm trong cụm số liệu (đã có gap riêng), không phải sát
             logo như trước — margin-left thừa sẽ đẩy lệch cả dải ticker. */
          padding: 4px 10px;
          white-space: nowrap;
          flex: 0 0 auto;
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
        /* Trên điện thoại chỉ giữ trạng thái; lý do ("Phiên chiều") làm pill
           xuống 2 dòng trong dải ticker. */
        @media (max-width: 640px) {
          .market-badge .market-reason { display: none; }
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
