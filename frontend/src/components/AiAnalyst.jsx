import { useState, useRef, useEffect } from 'react';
import {
  Cpu,
  Send,
  Activity,
  TrendingUp,
  BookOpen,
  Newspaper,
  AlertTriangle,
  MessageSquare,
  Compass,
  GitCompare,
  HelpCircle,
  ShieldAlert,
} from 'lucide-react';

const ERROR_LABELS = {
  missing_api_key: 'Chưa cấu hình Gemini API Key.',
  invalid_api_key: 'API Key không hợp lệ. Kiểm tra lại tại aistudio.google.com/apikey.',
  quota_exceeded: 'Đã hết hạn ngạch Gemini hôm nay. Thử lại sau hoặc nâng tier.',
  network_error: 'Lỗi kết nối tới Gemini. Kiểm tra mạng.',
  api_error: 'Lỗi từ Gemini API. Xem chi tiết bên dưới.',
};

/**
 * AI đọc giúp số liệu của mã đang xem.
 *
 * Bản cũ có ô "Khuyến nghị: MUA MẠNH", "Độ tin cậy 85%", giá mục tiêu và mức cắt
 * lỗ. Với người mới, đó chính là lệnh mua bán — mà một mô hình ngôn ngữ đọc vài
 * chỉ báo không có căn cứ nào đủ chắc để ra lệnh. Bản này chỉ giải thích: dữ liệu
 * nói gì, chỗ nào mâu thuẫn, rủi ro gì, và câu hỏi người đọc nên tự trả lời.
 * Backend (verdict_guard) lọc thêm một lớp phòng khi AI không nghe prompt.
 */
const TEXT_SECTIONS = [
  { key: 'tong_quan', label: 'Tổng quan', Icon: Compass },
  { key: 'ky_thuat', label: 'Chỉ báo kỹ thuật nói gì', Icon: Activity },
  { key: 'xu_huong', label: 'Xu hướng', Icon: TrendingUp },
  { key: 'co_ban', label: 'Chỉ số cơ bản nói gì', Icon: BookOpen },
  { key: 'tin_tuc', label: 'Tin tức', Icon: Newspaper },
  { key: 'mau_thuan', label: 'Chỗ dữ liệu mâu thuẫn', Icon: GitCompare },
];

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

  const analysis = analysisData?.analysis || {};
  const risks = Array.isArray(analysis.rui_ro) ? analysis.rui_ro : [];
  const questions = Array.isArray(analysis.cau_hoi_tu_hoi) ? analysis.cau_hoi_tu_hoi : [];
  const sections = TEXT_SECTIONS.filter((s) => analysis[s.key]);
  // Lỗi (thiếu key, hết hạn ngạch...) đã có banner riêng; không lặp lại thành một "đoạn giải thích".
  const hasContent = !analysis.error && (sections.length > 0 || risks.length > 0 || questions.length > 0);

  return (
    <div className="glass-panel column-ai">
      <div className="panel-header">
        <div className="panel-title">
          <Cpu className="logo-icon" size={18} />
          <span>AI giải thích</span>
        </div>
        <button
          className={`btn btn-primary btn-sm ${isAnalyzing ? 'disabled' : ''}`}
          onClick={onRunAnalysis}
          disabled={isAnalyzing}
          style={{ padding: '6px 12px', fontSize: '12px' }}
        >
          {isAnalyzing ? (
            <div className="loading-dots" style={{ display: 'inline-block' }}>
              Đang đọc số liệu<span>.</span><span>.</span><span>.</span>
            </div>
          ) : 'Giải thích mã này'}
        </button>
      </div>

      <div className="panel-content ai-scrollable">
        {analysis.error ? (
          <div className="ai-error-banner">
            <AlertTriangle size={14} />
            <div className="ai-error-body">
              <div className="ai-error-title">{ERROR_LABELS[analysis.error] || 'Lỗi không xác định.'}</div>
              {analysis.error_detail ? <div className="ai-error-detail">{analysis.error_detail}</div> : null}
            </div>
          </div>
        ) : null}

        {!analysisData ? (
          <div className="empty-ai-state">
            Bấm "Giải thích mã này" để AI đọc giúp chỉ báo kỹ thuật, chỉ số cơ bản và tin tức
            của mã đang xem bằng tiếng Việt dễ hiểu.
            <span className="ai-promise">
              AI không khuyên mua hay bán, không chấm điểm, không đưa giá mục tiêu.
            </span>
          </div>
        ) : null}

        {hasContent ? (
          <div className="ai-details-section">
            {sections.map(({ key, label, Icon }) => (
              <div key={key} className="ai-detail-block">
                <div className="block-title">
                  <Icon size={14} className="text-accent" /> {label}
                </div>
                <p className="block-text">{analysis[key]}</p>
              </div>
            ))}

            {risks.length > 0 ? (
              <div className="ai-detail-block">
                <div className="block-title">
                  <ShieldAlert size={14} className="text-sell" /> Rủi ro cần biết
                </div>
                <ul className="ai-list">
                  {risks.map((text, i) => (
                    <li key={i}>{text}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {questions.length > 0 ? (
              <div className="ai-detail-block">
                <div className="block-title">
                  <HelpCircle size={14} className="text-accent" /> Câu hỏi để bạn tự trả lời
                </div>
                <ul className="ai-list">
                  {questions.map((text, i) => (
                    <li key={i}>{text}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {analysis.ghi_chu_loc ? <p className="ai-filter-note">{analysis.ghi_chu_loc}</p> : null}
            <p className="ai-disclaimer">
              Phần diễn giải do AI viết từ số liệu và có thể sai. Không phải khuyến nghị đầu tư —
              quyết định là của bạn.
            </p>
          </div>
        ) : null}

        {/* AI Chatbox */}
        <div className="chatbox-container">
          <div className="chatbox-header">
            <MessageSquare size={14} />
            <span>Hỏi AI về số liệu</span>
          </div>

          <div className="chatbox-messages">
            <div className="message ai">
              Xin chào! Hỏi tôi về số liệu của mã này, ví dụ: "RSI 70 nghĩa là gì?" hay "Vì sao
              P/E cao hơn ngành?". Tôi giải thích, không khuyên mua hay bán.
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
        .empty-ai-state {
          text-align: center;
          color: var(--text-muted);
          font-size: 13px;
          padding: 20px 10px;
          line-height: 1.5;
          background: rgba(255, 255, 255, 0.02);
          border: 1px solid var(--border-color);
          border-radius: 12px;
        }
        .ai-promise {
          display: block;
          margin-top: 8px;
          font-size: 11px;
          opacity: 0.85;
        }
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
        .ai-list {
          margin: 0;
          padding-left: 18px;
          font-size: 12px;
          color: var(--text-secondary);
          line-height: 1.6;
        }
        .ai-filter-note {
          margin: 0;
          font-size: 10.5px;
          line-height: 1.5;
          color: var(--color-hold, #f59e0b);
        }
        .ai-disclaimer {
          margin: 0;
          font-size: 10px;
          line-height: 1.5;
          color: var(--text-muted);
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
          white-space: pre-line;
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
