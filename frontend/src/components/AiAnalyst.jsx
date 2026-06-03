import React, { useState, useRef, useEffect } from 'react';
import { Cpu, Send, TrendingUp, ShieldAlert, Award, MessageSquare, BookOpen, Newspaper, AlertTriangle } from 'lucide-react';

const ERROR_LABELS = {
  missing_api_key: 'Chưa cấu hình Gemini API Key.',
  invalid_api_key: 'API Key không hợp lệ. Kiểm tra lại tại aistudio.google.com/apikey.',
  quota_exceeded: 'Đã hết hạn ngạch Gemini hôm nay. Thử lại sau hoặc nâng tier.',
  network_error: 'Lỗi kết nối tới Gemini. Kiểm tra mạng.',
  api_error: 'Lỗi từ Gemini API. Xem chi tiết bên dưới.',
};

export default function AiAnalyst({ analysisData, isAnalyzing, onRunAnalysis, chatMessages, onSendMessage, isChatting }) {
  const [question, setQuestion] = useState('');
  const chatEndRef = useRef(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages, isChatting]);

  const handleSend = (e) => {
    e.preventDefault();
    if (!question.trim()) return;
    onSendMessage(question);
    setQuestion('');
  };

  const getRecommendationBadge = (rec) => {
    switch (rec) {
      case 'STRONG_BUY':
        return <span className="badge strong-buy">MUA MẠNH</span>;
      case 'BUY':
        return <span className="badge buy">MUA</span>;
      case 'SELL':
        return <span className="badge sell">BÁN</span>;
      case 'STRONG_SELL':
        return <span className="badge strong-sell">BÁN MẠNH</span>;
      case 'HOLD':
      default:
        return <span className="badge hold">NẮM GIỮ</span>;
    }
  };

  const analysis = analysisData?.analysis || {};

  return (
    <div className="glass-panel column-ai">
      <div className="panel-header">
        <div className="panel-title">
          <Cpu className="logo-icon" size={18} />
          <span>AI Analyst Brain</span>
        </div>
        <button 
          className={`btn btn-primary btn-sm ${isAnalyzing ? 'disabled' : ''}`}
          onClick={onRunAnalysis}
          disabled={isAnalyzing}
          style={{ padding: '6px 12px', fontSize: '12px' }}
        >
          {isAnalyzing ? (
            <div className="loading-dots" style={{ display: 'inline-block' }}>
              Đang phân tích<span>.</span><span>.</span><span>.</span>
            </div>
          ) : 'Phân tích AI'}
        </button>
      </div>

      <div className="panel-content ai-scrollable">
        {/* AI Error Banner */}
        {analysis.error ? (
          <div className="ai-error-banner">
            <AlertTriangle size={14} />
            <div className="ai-error-body">
              <div className="ai-error-title">{ERROR_LABELS[analysis.error] || 'Lỗi không xác định.'}</div>
              {analysis.error_detail ? <div className="ai-error-detail">{analysis.error_detail}</div> : null}
            </div>
          </div>
        ) : null}
        {/* Recommendation Panel */}
        <div className="ai-report-card">
          {analysisData ? (
            <div className="ai-metrics-grid">
              <div className="ai-metric-box main-badge-box">
                <span className="metric-label">Khuyến Nghị</span>
                <span className="metric-value">{getRecommendationBadge(analysis.recommendation)}</span>
              </div>
              <div className="ai-metric-box">
                <span className="metric-label">Độ Tin Cậy</span>
                <span className="metric-value font-display text-accent" style={{ fontSize: '20px', fontWeight: 'bold' }}>
                  {analysis.confidence || 0}%
                </span>
              </div>
              <div className="ai-metric-box">
                <span className="metric-label">Mục Tiêu</span>
                <span className="metric-value text-buy" style={{ fontSize: '15px', fontWeight: '600' }}>
                  {analysis.target_price ? Number(analysis.target_price).toLocaleString() : 'N/A'}
                </span>
              </div>
              <div className="ai-metric-box">
                <span className="metric-label">Cắt Lỗ</span>
                <span className="metric-value text-sell" style={{ fontSize: '15px', fontWeight: '600' }}>
                  {analysis.stop_loss ? Number(analysis.stop_loss).toLocaleString() : 'N/A'}
                </span>
              </div>
            </div>
          ) : (
            <div className="empty-ai-state">
              Bấm nút "Phân tích AI" để nhận tín hiệu đầu tư và định giá cổ phiếu.
            </div>
          )}
        </div>

        {analysisData && (
          <div className="ai-details-section">
            <div className="ai-detail-block">
              <div className="block-title"><Award size={14} className="text-accent" /> Tóm tắt đánh giá</div>
              <p className="block-text">{analysis.summary}</p>
            </div>
            <div className="ai-detail-block">
              <div className="block-title"><TrendingUp size={14} className="text-buy" /> Phân tích kỹ thuật</div>
              <p className="block-text">{analysis.technical_analysis}</p>
            </div>
            {analysis.fundamental_analysis && (
              <div className="ai-detail-block">
                <div className="block-title"><BookOpen size={14} className="text-accent" /> Phân tích cơ bản</div>
                <p className="block-text">{analysis.fundamental_analysis}</p>
              </div>
            )}
            {analysis.news_sentiment && (
              <div className="ai-detail-block">
                <div className="block-title"><Newspaper size={14} className="text-accent" /> Bối cảnh tin tức</div>
                <p className="block-text">{analysis.news_sentiment}</p>
              </div>
            )}
            {analysis.trend_analysis && (
              <div className="ai-detail-block">
                <div className="block-title"><TrendingUp size={14} className="text-accent" /> Xu hướng</div>
                <p className="block-text">{analysis.trend_analysis}</p>
              </div>
            )}
            <div className="ai-detail-block">
              <div className="block-title"><ShieldAlert size={14} className="text-sell" /> Kế hoạch hành động</div>
              <p className="block-text">{analysis.action_plan}</p>
            </div>
          </div>
        )}

        {/* AI Chatbox */}
        <div className="chatbox-container">
          <div className="chatbox-header">
            <MessageSquare size={14} />
            <span>Thảo luận cùng AI</span>
          </div>
          
          <div className="chatbox-messages">
            <div className="message ai">
              Xin chào! Hãy hỏi tôi bất kỳ điều gì về cổ phiếu này (Ví dụ: "Có nên mua đuổi không?", "Các ngưỡng cản mạnh tiếp theo ở đâu?").
            </div>
            {chatMessages.map((msg, i) => (
              <div key={i} className={`message ${msg.role}`}>
                {msg.text}
              </div>
            ))}
            {isChatting && (
              <div className="message ai typing">
                <div className="loading-dots">AI đang trả lời<span>.</span><span>.</span><span>.</span></div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          <form onSubmit={handleSend} className="chatbox-input-form">
            <input
              type="text"
              placeholder="Nhập câu hỏi..."
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              disabled={isAnalyzing || isChatting || !analysisData}
            />
            <button type="submit" disabled={isAnalyzing || isChatting || !question.trim() || !analysisData}>
              <Send size={14} />
            </button>
          </form>
        </div>
      </div>

      <style>{`
        .column-ai {
          height: 100%;
          display: flex;
          flex-direction: column;
          min-height: 0;
        }
        .ai-scrollable {
          overflow-y: auto;
          display: flex;
          flex-direction: column;
          gap: 16px;
        }
        .ai-error-banner {
          display: flex;
          gap: 10px;
          padding: 10px 12px;
          background: rgba(244, 63, 94, 0.1);
          border: 1px solid rgba(244, 63, 94, 0.35);
          border-radius: 8px;
          color: #fda4af;
          align-items: flex-start;
        }
        .ai-error-body { flex-grow: 1; min-width: 0; }
        .ai-error-title { font-size: 12px; font-weight: 600; margin-bottom: 2px; }
        .ai-error-detail {
          font-size: 10px;
          color: var(--text-muted);
          font-family: ui-monospace, monospace;
          word-break: break-all;
        }
        .ai-report-card {
          background: rgba(255, 255, 255, 0.02);
          border: 1px solid var(--border-color);
          border-radius: 12px;
          padding: 12px;
        }
        .empty-ai-state {
          text-align: center;
          color: var(--text-muted);
          font-size: 13px;
          padding: 20px 10px;
          line-height: 1.5;
        }
        .ai-metrics-grid {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 10px;
        }
        .ai-metric-box {
          background: rgba(0, 0, 0, 0.2);
          border: 1px solid rgba(255, 255, 255, 0.04);
          border-radius: 8px;
          padding: 10px;
          display: flex;
          flex-direction: column;
          justify-content: center;
          align-items: center;
          gap: 4px;
        }
        .main-badge-box {
          grid-column: span 2;
          padding: 14px;
        }
        .metric-label {
          font-size: 10px;
          color: var(--text-muted);
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .metric-value {
          font-size: 14px;
          font-weight: 500;
        }
        .badge {
          padding: 4px 10px;
          border-radius: 6px;
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 12px;
          letter-spacing: 0.5px;
        }
        .badge.strong-buy {
          background: rgba(16, 185, 129, 0.2);
          color: var(--color-buy);
          border: 1px solid var(--color-buy);
          box-shadow: 0 0 10px rgba(16, 185, 129, 0.1);
        }
        .badge.buy {
          background: rgba(16, 185, 129, 0.1);
          color: var(--color-buy);
          border: 1px solid rgba(16, 185, 129, 0.5);
        }
        .badge.sell {
          background: rgba(244, 63, 94, 0.1);
          color: var(--color-sell);
          border: 1px solid rgba(244, 63, 94, 0.5);
        }
        .badge.strong-sell {
          background: rgba(244, 63, 94, 0.2);
          color: var(--color-sell);
          border: 1px solid var(--color-sell);
          box-shadow: 0 0 10px rgba(244, 63, 94, 0.1);
        }
        .badge.hold {
          background: rgba(245, 158, 11, 0.15);
          color: var(--color-hold);
          border: 1px solid var(--color-hold);
        }
        .text-buy { color: var(--color-buy); }
        .text-sell { color: var(--color-sell); }
        .text-accent { color: var(--color-accent); }
        
        .ai-details-section {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .ai-detail-block {
          background: rgba(255, 255, 255, 0.01);
          border-left: 2px solid var(--border-color);
          padding-left: 10px;
        }
        .ai-detail-block:hover {
          border-left-color: var(--color-accent);
        }
        .block-title {
          font-family: var(--font-display);
          font-size: 12px;
          font-weight: 600;
          margin-bottom: 4px;
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .block-text {
          font-size: 12px;
          color: var(--text-secondary);
          line-height: 1.6;
        }
        
        /* Chatbox */
        .chatbox-container {
          background: rgba(0, 0, 0, 0.3);
          border: 1px solid var(--border-color);
          border-radius: 12px;
          display: flex;
          flex-direction: column;
          height: 250px;
          flex-shrink: 0;
          overflow: hidden;
        }
        .chatbox-header {
          background: rgba(255, 255, 255, 0.02);
          border-bottom: 1px solid var(--border-color);
          padding: 8px 12px;
          font-size: 11px;
          font-weight: 600;
          color: var(--text-secondary);
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .chatbox-messages {
          flex-grow: 1;
          overflow-y: auto;
          padding: 10px;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .message {
          max-width: 85%;
          padding: 8px 12px;
          border-radius: 10px;
          font-size: 11px;
          line-height: 1.4;
          word-break: break-word;
        }
        .message.ai {
          background: rgba(255, 255, 255, 0.05);
          color: var(--text-primary);
          align-self: flex-start;
          border-bottom-left-radius: 2px;
          border: 1px solid rgba(255, 255, 255, 0.03);
        }
        .message.user {
          background: rgba(6, 182, 212, 0.15);
          color: #e2f8ff;
          align-self: flex-end;
          border-bottom-right-radius: 2px;
          border: 1px solid rgba(6, 182, 212, 0.2);
        }
        .message.typing {
          opacity: 0.7;
        }
        .chatbox-input-form {
          display: flex;
          border-top: 1px solid var(--border-color);
          background: rgba(0, 0, 0, 0.2);
        }
        .chatbox-input-form input {
          flex-grow: 1;
          background: transparent;
          border: none;
          padding: 10px 12px;
          color: var(--text-primary);
          font-size: 11px;
          font-family: var(--font-main);
        }
        .chatbox-input-form input:focus {
          outline: none;
        }
        .chatbox-input-form button {
          background: transparent;
          border: none;
          color: var(--color-accent);
          padding: 0 14px;
          cursor: pointer;
          transition: all 0.2s;
          display: flex;
          align-items: center;
        }
        .chatbox-input-form button:hover:not(:disabled) {
          color: #fff;
          transform: scale(1.1);
        }
        .chatbox-input-form button:disabled {
          color: var(--text-muted);
          cursor: not-allowed;
        }
      `}</style>
    </div>
  );
}
