import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Bell, BellRing, Trash2, Plus, RefreshCw, AlertTriangle, CheckCircle2, Search, Newspaper } from 'lucide-react';

const CONDITIONS = [
  { id: 'price_above', label: 'Giá vượt', needsThreshold: true, unit: 'đ', placeholder: 'VD: 80000' },
  { id: 'price_below', label: 'Giá xuống dưới', needsThreshold: true, unit: 'đ', placeholder: 'VD: 65000' },
  { id: 'rsi_above', label: 'RSI vượt', needsThreshold: true, unit: '', placeholder: '0 - 100, VD: 70' },
  { id: 'rsi_below', label: 'RSI xuống dưới', needsThreshold: true, unit: '', placeholder: '0 - 100, VD: 30' },
  { id: 'ema_cross_up', label: 'EMA cắt lên', needsThreshold: false, unit: '', placeholder: '' },
  { id: 'ema_cross_down', label: 'EMA cắt xuống', needsThreshold: false, unit: '', placeholder: '' },
  { id: 'news_new', label: 'Có tin mới', needsThreshold: false, unit: '', placeholder: '' },
];

const CONDITION_MAP = CONDITIONS.reduce((acc, c) => {
  acc[c.id] = c;
  return acc;
}, {});

const fmtNumber = (v) => {
  if (v === null || v === undefined || v === '') return '';
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return n.toLocaleString('vi-VN');
};

const describeAlert = (alert) => {
  const cond = CONDITION_MAP[alert.condition];
  // Rule mang điều kiện đã gỡ (vd "AI đổi tín hiệu") vẫn có thể còn trong DB cũ.
  if (!cond) return 'Điều kiện cũ, không còn được kiểm tra';
  if (!cond.needsThreshold) return cond.label;
  if (alert.condition === 'rsi_above' || alert.condition === 'rsi_below') {
    return `${cond.label} ${alert.threshold}`;
  }
  return `${cond.label} ${fmtNumber(alert.threshold)}${cond.unit ? ` ${cond.unit}` : ''}`;
};

// Poll thưa khi thị trường đóng: giá không đổi thì check chỉ tốn rate limit của
// vnstock (20 req/phút, dùng chung với chart và heatmap).
const CHECK_INTERVAL_OPEN_MS = 60_000;
const CHECK_INTERVAL_CLOSED_MS = 10 * 60_000;

const notifyTriggered = (triggered) => {
  if (!triggered.length) return;
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
  const names = triggered.map((t) => t.symbol || t.alert?.symbol || '?').join(', ');
  try {
    new Notification(`${triggered.length} cảnh báo kích hoạt`, {
      body: names,
      tag: 'vn-stock-alert',
    });
  } catch {
    // Một số trình duyệt chặn Notification ngoài ngữ cảnh service worker.
  }
};

export default function AlertsManager({ apiBase, marketOpen = false }) {
  const [alerts, setAlerts] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  // Form state
  const [symbolInput, setSymbolInput] = useState('');
  const [selectedSymbol, setSelectedSymbol] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [condition, setCondition] = useState('price_above');
  const [threshold, setThreshold] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState(null);

  // Bật theo dõi tin cho cả danh mục thật (một nút, không phải tạo từng rule).
  const [watchState, setWatchState] = useState(null);
  const [isWatching, setIsWatching] = useState(false);

  // Check state
  const [isChecking, setIsChecking] = useState(false);
  const [checkResult, setCheckResult] = useState(null);
  const [autoCheck, setAutoCheck] = useState(() => {
    try {
      return localStorage.getItem('alerts_auto_check') !== 'off';
    } catch {
      return true;
    }
  });
  const [lastCheckedAt, setLastCheckedAt] = useState(null);

  const searchTimer = useRef(null);
  const suggestionsBoxRef = useRef(null);

  const fetchAlerts = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/alerts`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setAlerts(Array.isArray(data) ? data : data.alerts || []);
    } catch (e) {
      setError(e.message || 'Không tải được danh sách cảnh báo');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchAlerts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Symbol autocomplete
  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    const q = symbolInput.trim();
    if (!q || q === selectedSymbol) {
      setSuggestions([]);
      return;
    }
    searchTimer.current = setTimeout(async () => {
      try {
        const res = await fetch(`${apiBase}/stocks/search?query=${encodeURIComponent(q)}`);
        if (!res.ok) return;
        const data = await res.json();
        const list = Array.isArray(data) ? data : data.results || data.items || [];
        setSuggestions(list.slice(0, 8));
      } catch {
        setSuggestions([]);
      }
    }, 200);
    return () => searchTimer.current && clearTimeout(searchTimer.current);
  }, [symbolInput, selectedSymbol, apiBase]);

  // Close suggestions on outside click
  useEffect(() => {
    const onClick = (e) => {
      if (suggestionsBoxRef.current && !suggestionsBoxRef.current.contains(e.target)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  const pickSymbol = (s) => {
    const code = (s.symbol || s.code || s.ticker || s).toString().toUpperCase();
    setSelectedSymbol(code);
    setSymbolInput(code);
    setShowSuggestions(false);
  };

  const conditionMeta = CONDITION_MAP[condition];

  const canSubmit = useMemo(() => {
    const sym = (selectedSymbol || symbolInput).trim().toUpperCase();
    if (!sym) return false;
    if (conditionMeta?.needsThreshold) {
      const n = Number(threshold);
      if (!threshold || Number.isNaN(n)) return false;
      if ((condition === 'rsi_above' || condition === 'rsi_below') && (n < 0 || n > 100)) return false;
    }
    return true;
  }, [selectedSymbol, symbolInput, conditionMeta, threshold, condition]);

  const createAlert = async (e) => {
    e?.preventDefault?.();
    if (!canSubmit) return;
    setIsCreating(true);
    setCreateError(null);
    try {
      const sym = (selectedSymbol || symbolInput).trim().toUpperCase();
      const body = { symbol: sym, condition };
      if (conditionMeta?.needsThreshold) body.threshold = Number(threshold);
      const res = await fetch(`${apiBase}/alerts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
      // Reset form
      setSymbolInput('');
      setSelectedSymbol('');
      setThreshold('');
      setCondition('price_above');
      setSuggestions([]);
      await fetchAlerts();
    } catch (err) {
      setCreateError(err.message || 'Không tạo được cảnh báo');
    } finally {
      setIsCreating(false);
    }
  };

  const watchPortfolioNews = async () => {
    setIsWatching(true);
    setWatchState(null);
    try {
      const res = await fetch(`${apiBase}/alerts/watch-portfolio`, { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      const added = data.created_count || 0;
      setWatchState({
        ok: true,
        text: added
          ? `Đã bật theo dõi tin cho ${added} mã: ${data.created.map((c) => c.symbol).join(', ')}`
          : 'Tất cả mã trong danh mục đã được theo dõi tin từ trước.',
      });
      await fetchAlerts();
    } catch (err) {
      setWatchState({ ok: false, text: err.message || 'Không bật được theo dõi tin' });
    } finally {
      setIsWatching(false);
    }
  };

  const deleteAlert = async (id) => {
    try {
      const res = await fetch(`${apiBase}/alerts/${id}`, { method: 'DELETE' });
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
      setAlerts((prev) => prev.filter((a) => (a.id ?? a._id) !== id));
    } catch (err) {
      setError(err.message || 'Không xóa được cảnh báo');
    }
  };

  // silent = lượt tự động: không hiện spinner, và chỉ báo khi thực sự có rule bắn
  // (nếu không, banner "chưa có cảnh báo nào" sẽ nhấp nháy mỗi phút).
  const runCheck = useCallback(
    async ({ silent = false } = {}) => {
      if (!silent) {
        setIsChecking(true);
        setCheckResult(null);
      }
      try {
        const res = await fetch(`${apiBase}/alerts/check`, { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        const triggered = Array.isArray(data) ? data : data.triggered || data.results || [];
        if (!silent || triggered.length) {
          setCheckResult({ triggered, raw: data });
        }
        if (triggered.length) notifyTriggered(triggered);
        setLastCheckedAt(Date.now());
        await fetchAlerts();
      } catch (err) {
        if (!silent) setCheckResult({ triggered: [], error: err.message || 'Lỗi khi check' });
      } finally {
        if (!silent) setIsChecking(false);
      }
    },
    // fetchAlerts được khai báo lại mỗi render nhưng chỉ đọc apiBase — bỏ khỏi deps
    // để interval bên dưới không bị dựng lại liên tục.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [apiBase],
  );

  const toggleAutoCheck = async () => {
    const next = !autoCheck;
    setAutoCheck(next);
    try {
      localStorage.setItem('alerts_auto_check', next ? 'on' : 'off');
    } catch {
      // localStorage bị chặn — tính năng vẫn chạy trong phiên này.
    }
    if (next && typeof Notification !== 'undefined' && Notification.permission === 'default') {
      try {
        await Notification.requestPermission();
      } catch {
        // Người dùng từ chối: cảnh báo vẫn hiện trong panel, chỉ không có popup.
      }
    }
  };

  // Tự kiểm tra định kỳ. Dừng hẳn khi tab ẩn hoặc không còn rule active.
  const hasActiveAlerts = alerts.some((a) => a.active !== false);
  useEffect(() => {
    if (!autoCheck || !hasActiveAlerts) return undefined;

    let cancelled = false;
    const tick = () => {
      if (cancelled || document.hidden) return;
      runCheck({ silent: true });
    };
    const intervalMs = marketOpen ? CHECK_INTERVAL_OPEN_MS : CHECK_INTERVAL_CLOSED_MS;
    const id = setInterval(tick, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [autoCheck, hasActiveAlerts, marketOpen, runCheck]);

  const triggeredCount = alerts.filter((a) => a.triggered_at || a.active === false).length;

  return (
    <div className="glass-panel">
      <div className="panel-header">
        <div className="panel-title">
          <Bell size={16} className="text-accent" />
          <span>Cảnh báo</span>
          <span className="alert-count-badge">{alerts.length}</span>
          {triggeredCount > 0 ? (
            <span className="alert-count-badge triggered">{triggeredCount} kích hoạt</span>
          ) : null}
        </div>
        <div className="alert-header-actions">
          <button
            type="button"
            className={`alert-auto-toggle ${autoCheck ? 'on' : ''}`}
            onClick={toggleAutoCheck}
            title={
              autoCheck
                ? `Đang tự kiểm tra mỗi ${marketOpen ? '1 phút' : '10 phút'} khi tab đang mở`
                : 'Bật tự kiểm tra định kỳ'
            }
          >
            {autoCheck ? 'Tự động: BẬT' : 'Tự động: TẮT'}
          </button>
          <button
            type="button"
            className="alert-check-btn"
            onClick={() => runCheck()}
            disabled={isChecking || alerts.length === 0}
            title="Kiểm tra các điều kiện cảnh báo ngay"
          >
            <RefreshCw size={11} className={isChecking ? 'spin' : ''} />
            {isChecking ? 'Đang kiểm...' : 'Check ngay'}
          </button>
        </div>
      </div>

      <div className="panel-content alert-content">
        {error ? (
          <div className="alert-error-banner">
            <AlertTriangle size={12} />
            <span>{error}</span>
          </div>
        ) : null}

        {autoCheck && hasActiveAlerts ? (
          <div className="alert-auto-status">
            Tự kiểm tra mỗi {marketOpen ? '1 phút' : '10 phút'}
            {lastCheckedAt
              ? ` · lần cuối ${new Date(lastCheckedAt).toLocaleTimeString('vi-VN', {
                  hour: '2-digit',
                  minute: '2-digit',
                })}`
              : ''}
          </div>
        ) : null}

        {checkResult ? (
          <div className={`alert-check-result ${checkResult.error ? 'error' : checkResult.triggered.length ? 'hit' : 'empty'}`}>
            {checkResult.error ? (
              <>
                <AlertTriangle size={12} />
                <span>{checkResult.error}</span>
              </>
            ) : checkResult.triggered.length > 0 ? (
              <>
                <BellRing size={12} />
                <div className="alert-check-body">
                  <span>
                    {checkResult.triggered.length} cảnh báo vừa kích hoạt:{' '}
                    {checkResult.triggered
                      .slice(0, 5)
                      .map((t) => t.symbol || t.alert?.symbol || '?')
                      .join(', ')}
                  </span>
                  {/* Cảnh báo tin mà chỉ hiện tên mã thì người dùng vẫn phải đi mò
                      xem tin gì — nên in luôn tiêu đề tin đã kích hoạt. */}
                  {checkResult.triggered
                    .filter((t) => t.context?.news?.title)
                    .slice(0, 3)
                    .map((t) => (
                      <span key={t.id} className="alert-check-news">
                        <Newspaper size={10} />
                        <span>
                          <b>{t.symbol}</b> — {t.context.news.title}
                        </span>
                      </span>
                    ))}
                </div>
              </>
            ) : (
              <>
                <CheckCircle2 size={12} />
                <span>Chưa có cảnh báo nào kích hoạt.</span>
              </>
            )}
            <button type="button" className="alert-check-dismiss" onClick={() => setCheckResult(null)}>×</button>
          </div>
        ) : null}

        <div className="alert-watch">
          <button
            type="button"
            className="alert-watch-btn"
            onClick={watchPortfolioNews}
            disabled={isWatching}
          >
            <Newspaper size={12} className={isWatching ? 'spin' : ''} />
            <span>{isWatching ? 'Đang bật...' : 'Báo tin mới cho danh mục của tôi'}</span>
          </button>
          {watchState ? (
            <span className={`alert-watch-msg ${watchState.ok ? '' : 'err'}`}>{watchState.text}</span>
          ) : (
            <span className="alert-watch-msg">
              Tạo cảnh báo "có tin mới" cho mọi mã bạn đang nắm.
            </span>
          )}
        </div>

        {/* Alert list */}
        <div className="alert-list">
          {isLoading && alerts.length === 0 ? (
            <div className="alert-empty">Đang tải...</div>
          ) : alerts.length === 0 ? (
            <div className="alert-empty">Chưa có cảnh báo nào. Tạo cảnh báo đầu tiên bên dưới.</div>
          ) : (
            alerts.map((a) => {
              const id = a.id ?? a._id;
              const isTriggered = a.triggered || a.status === 'triggered';
              return (
                <div key={id} className={`alert-row ${isTriggered ? 'triggered' : ''}`}>
                  <div className="alert-row-main">
                    <span className="alert-symbol">{a.symbol}</span>
                    <span className="alert-condition">{describeAlert(a)}</span>
                  </div>
                  <div className="alert-row-side">
                    <span className={`alert-status ${isTriggered ? 'fired' : 'watching'}`}>
                      {isTriggered ? (
                        <>
                          <BellRing size={10} /> Đã trigger
                        </>
                      ) : (
                        <>
                          <Bell size={10} /> Đang theo dõi
                        </>
                      )}
                    </span>
                    <button
                      type="button"
                      className="alert-delete-btn"
                      onClick={() => deleteAlert(id)}
                      title="Xóa cảnh báo"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Create form */}
        <form className="alert-form" onSubmit={createAlert}>
          <div className="alert-form-header">
            <Plus size={12} /> <span>Cảnh báo mới</span>
          </div>

          <div className="alert-form-row">
            <label className="alert-field" ref={suggestionsBoxRef}>
              <span className="alert-field-label">Mã CK</span>
              <div className="alert-symbol-wrap">
                <Search size={11} className="alert-symbol-icon" />
                <input
                  type="text"
                  value={symbolInput}
                  onChange={(e) => {
                    const v = e.target.value.toUpperCase();
                    setSymbolInput(v);
                    setSelectedSymbol('');
                    setShowSuggestions(true);
                  }}
                  onFocus={() => setShowSuggestions(true)}
                  placeholder="FPT, VNM, HPG..."
                  autoComplete="off"
                />
                {showSuggestions && suggestions.length > 0 ? (
                  <div className="alert-suggestions">
                    {suggestions.map((s, i) => {
                      const code = (s.symbol || s.code || s.ticker || s).toString().toUpperCase();
                      const name = s.name || s.organ_name || s.companyName || '';
                      return (
                        <button
                          type="button"
                          key={`${code}-${i}`}
                          className="alert-suggestion"
                          onClick={() => pickSymbol(s)}
                        >
                          <span className="alert-suggestion-code">{code}</span>
                          {name ? <span className="alert-suggestion-name">{name}</span> : null}
                        </button>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            </label>

            <label className="alert-field">
              <span className="alert-field-label">Điều kiện</span>
              <select value={condition} onChange={(e) => setCondition(e.target.value)}>
                {CONDITIONS.map((c) => (
                  <option key={c.id} value={c.id}>{c.label}</option>
                ))}
              </select>
            </label>

            <label className={`alert-field ${conditionMeta?.needsThreshold ? '' : 'disabled'}`}>
              <span className="alert-field-label">Ngưỡng{conditionMeta?.unit ? ` (${conditionMeta.unit})` : ''}</span>
              <input
                type="number"
                step="any"
                value={threshold}
                onChange={(e) => setThreshold(e.target.value)}
                placeholder={conditionMeta?.needsThreshold ? conditionMeta.placeholder : '—'}
                disabled={!conditionMeta?.needsThreshold}
              />
            </label>

            <button type="submit" className="alert-submit-btn" disabled={!canSubmit || isCreating}>
              {isCreating ? '...' : 'Tạo'}
            </button>
          </div>

          {createError ? <div className="alert-form-error">{createError}</div> : null}
        </form>
      </div>

      <style>{`
        .alert-count-badge {
          background: rgba(6, 182, 212, 0.12);
          color: var(--color-accent);
          font-size: 10px;
          font-weight: 700;
          padding: 1px 6px;
          border-radius: 4px;
          font-family: var(--font-display);
        }
        .alert-count-badge.triggered {
          background: rgba(244, 63, 94, 0.15);
          color: var(--color-sell);
        }
        .alert-header-actions {
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .alert-auto-toggle {
          font-size: 9px;
          letter-spacing: 0.4px;
          padding: 3px 7px;
          border-radius: 999px;
          border: 1px solid var(--border-color);
          background: transparent;
          color: var(--text-muted);
          cursor: pointer;
        }
        .alert-auto-toggle.on {
          border-color: var(--color-buy);
          color: var(--color-buy);
        }
        .alert-auto-status {
          font-size: 9px;
          color: var(--text-muted);
          padding: 0 2px;
        }
        .alert-check-btn {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          background: rgba(6, 182, 212, 0.12);
          border: 1px solid rgba(6, 182, 212, 0.3);
          color: var(--color-accent);
          padding: 4px 10px;
          border-radius: 5px;
          font-size: 10px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.15s;
        }
        .alert-check-btn:hover:not(:disabled) {
          background: rgba(6, 182, 212, 0.2);
        }
        .alert-check-btn:disabled {
          opacity: 0.4;
          cursor: not-allowed;
        }
        .alert-check-btn .spin {
          animation: alert-spin 0.8s linear infinite;
        }
        @keyframes alert-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }

        .alert-content {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }

        .alert-error-banner {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 10px;
          background: rgba(244, 63, 94, 0.1);
          border: 1px solid rgba(244, 63, 94, 0.3);
          color: #fda4af;
          border-radius: 6px;
          font-size: 11px;
        }

        .alert-check-result {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 10px;
          border-radius: 6px;
          font-size: 11px;
          border: 1px solid var(--border-color);
        }
        .alert-check-result.hit {
          background: rgba(244, 63, 94, 0.1);
          border-color: rgba(244, 63, 94, 0.3);
          color: #fda4af;
        }
        .alert-check-result.empty {
          background: rgba(16, 185, 129, 0.08);
          border-color: rgba(16, 185, 129, 0.25);
          color: #86efac;
        }
        .alert-check-result.error {
          background: rgba(244, 63, 94, 0.1);
          border-color: rgba(244, 63, 94, 0.3);
          color: #fda4af;
        }
        .alert-check-dismiss {
          margin-left: auto;
          background: transparent;
          border: none;
          color: inherit;
          opacity: 0.6;
          cursor: pointer;
          font-size: 14px;
          line-height: 1;
          padding: 0 2px;
        }
        .alert-check-dismiss:hover { opacity: 1; }

        .alert-list {
          display: flex;
          flex-direction: column;
          gap: 6px;
          max-height: 260px;
          overflow-y: auto;
        }
        .alert-empty {
          text-align: center;
          font-size: 12px;
          color: var(--text-muted);
          padding: 18px 10px;
          background: rgba(0, 0, 0, 0.2);
          border: 1px dashed var(--border-color);
          border-radius: 8px;
        }
        .alert-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          padding: 8px 10px;
          background: rgba(0, 0, 0, 0.25);
          border: 1px solid var(--border-color);
          border-radius: 8px;
          transition: all 0.15s;
        }
        .alert-row:hover {
          border-color: rgba(6, 182, 212, 0.3);
        }
        .alert-row.triggered {
          border-color: rgba(244, 63, 94, 0.4);
          background: rgba(244, 63, 94, 0.05);
        }
        .alert-row-main {
          display: flex;
          align-items: baseline;
          gap: 8px;
          min-width: 0;
          flex-grow: 1;
        }
        .alert-symbol {
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 13px;
          color: var(--text-primary);
          letter-spacing: 0.5px;
        }
        .alert-condition {
          font-size: 11px;
          color: var(--text-secondary);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .alert-row-side {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-shrink: 0;
        }
        .alert-status {
          display: inline-flex;
          align-items: center;
          gap: 3px;
          font-size: 10px;
          padding: 2px 6px;
          border-radius: 4px;
          font-weight: 600;
        }
        .alert-status.watching {
          background: rgba(6, 182, 212, 0.1);
          color: var(--color-accent);
          border: 1px solid rgba(6, 182, 212, 0.25);
        }
        .alert-status.fired {
          background: rgba(244, 63, 94, 0.12);
          color: var(--color-sell);
          border: 1px solid rgba(244, 63, 94, 0.35);
        }
        .alert-delete-btn {
          background: transparent;
          border: 1px solid transparent;
          color: var(--text-muted);
          padding: 3px 5px;
          border-radius: 4px;
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          transition: all 0.15s;
        }
        .alert-delete-btn:hover {
          background: rgba(244, 63, 94, 0.1);
          border-color: rgba(244, 63, 94, 0.3);
          color: var(--color-sell);
        }

        .alert-form {
          background: rgba(0, 0, 0, 0.3);
          border: 1px solid var(--border-color);
          border-radius: 8px;
          padding: 10px;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .alert-check-body { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
        .alert-check-news {
          display: flex;
          align-items: flex-start;
          gap: 5px;
          font-size: 10px;
          line-height: 1.5;
          opacity: 0.85;
        }
        .alert-check-news svg { flex: 0 0 auto; margin-top: 2px; }
        .alert-watch {
          display: flex;
          flex-direction: column;
          gap: 5px;
          padding: 9px 10px;
          border: 1px dashed var(--border-color);
          border-radius: 8px;
          background: rgba(0, 0, 0, 0.18);
        }
        .alert-watch-btn {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          padding: 7px 10px;
          border-radius: 7px;
          border: 1px solid var(--color-accent);
          background: rgba(6, 182, 212, 0.1);
          color: var(--color-accent);
          font-size: 11.5px;
          font-weight: 600;
          cursor: pointer;
        }
        .alert-watch-btn:disabled { opacity: 0.6; cursor: default; }
        .alert-watch-msg { font-size: 10px; line-height: 1.5; color: var(--text-muted); }
        .alert-watch-msg.err { color: var(--color-sell); }
        .alert-form-header {
          display: flex;
          align-items: center;
          gap: 5px;
          font-size: 11px;
          font-weight: 600;
          color: var(--color-accent);
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .alert-form-row {
          display: grid;
          grid-template-columns: 1.1fr 1.3fr 1fr auto;
          gap: 8px;
          align-items: flex-end;
        }
        .alert-field {
          display: flex;
          flex-direction: column;
          gap: 3px;
          min-width: 0;
          position: relative;
        }
        .alert-field.disabled {
          opacity: 0.55;
        }
        .alert-field-label {
          font-size: 9px;
          color: var(--text-muted);
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .alert-field input,
        .alert-field select {
          background: rgba(0, 0, 0, 0.35);
          border: 1px solid var(--border-color);
          color: var(--text-primary);
          padding: 6px 8px;
          border-radius: 5px;
          font-size: 12px;
          font-family: var(--font-display);
          width: 100%;
          box-sizing: border-box;
        }
        .alert-field input:focus,
        .alert-field select:focus {
          outline: none;
          border-color: var(--color-accent);
        }
        .alert-field input:disabled {
          cursor: not-allowed;
          background: rgba(0, 0, 0, 0.2);
        }

        .alert-symbol-wrap {
          position: relative;
        }
        .alert-symbol-icon {
          position: absolute;
          left: 7px;
          top: 50%;
          transform: translateY(-50%);
          color: var(--text-muted);
          pointer-events: none;
        }
        .alert-symbol-wrap input {
          padding-left: 22px;
        }
        .alert-suggestions {
          position: absolute;
          top: 100%;
          left: 0;
          right: 0;
          margin-top: 2px;
          background: #0d1117;
          border: 1px solid var(--border-color);
          border-radius: 6px;
          max-height: 180px;
          overflow-y: auto;
          z-index: 20;
          box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
        }
        .alert-suggestion {
          width: 100%;
          display: flex;
          flex-direction: column;
          gap: 1px;
          text-align: left;
          padding: 6px 9px;
          background: transparent;
          border: none;
          border-bottom: 1px solid rgba(255, 255, 255, 0.04);
          cursor: pointer;
          color: var(--text-primary);
        }
        .alert-suggestion:last-child { border-bottom: none; }
        .alert-suggestion:hover {
          background: rgba(6, 182, 212, 0.08);
        }
        .alert-suggestion-code {
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 12px;
          color: var(--color-accent);
        }
        .alert-suggestion-name {
          font-size: 10px;
          color: var(--text-muted);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .alert-submit-btn {
          background: rgba(6, 182, 212, 0.18);
          border: 1px solid rgba(6, 182, 212, 0.4);
          color: var(--color-accent);
          padding: 7px 14px;
          border-radius: 5px;
          font-size: 11px;
          font-weight: 700;
          cursor: pointer;
          transition: all 0.15s;
          height: fit-content;
        }
        .alert-submit-btn:hover:not(:disabled) {
          background: rgba(6, 182, 212, 0.28);
          color: #fff;
        }
        .alert-submit-btn:disabled {
          opacity: 0.45;
          cursor: not-allowed;
        }

        .alert-form-error {
          background: rgba(244, 63, 94, 0.1);
          border: 1px solid rgba(244, 63, 94, 0.3);
          color: #fda4af;
          padding: 5px 8px;
          border-radius: 5px;
          font-size: 10px;
        }

        @media (max-width: 720px) {
          .alert-form-row {
            grid-template-columns: 1fr 1fr;
          }
          .alert-submit-btn {
            grid-column: span 2;
          }
        }
      `}</style>
    </div>
  );
}
