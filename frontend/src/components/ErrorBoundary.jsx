import { Component } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

/**
 * Chặn lỗi render của một nhánh UI.
 *
 * Không có nó, một panel ném lỗi (schema dữ liệu đổi, field thiếu...) sẽ unmount
 * toàn bộ cây React và người dùng thấy màn hình trắng — mất luôn cả biểu đồ lẫn
 * danh mục vì một widget phụ. Bọc từng panel để lỗi chỉ giới hạn trong panel đó.
 *
 * Phải là class component: React chưa có hook tương đương componentDidCatch.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Giữ lại stack để debug; không có backend log nên console là nơi duy nhất.
    console.error(`[ErrorBoundary] ${this.props.name || 'component'} lỗi:`, error, info);
  }

  handleRetry = () => {
    this.setState({ error: null });
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="glass-panel eb-panel">
        <div className="eb-head">
          <AlertTriangle size={16} />
          <span>{this.props.name ? `Lỗi ở "${this.props.name}"` : 'Phần này gặp lỗi'}</span>
        </div>
        <p className="eb-desc">
          Các phần còn lại của ứng dụng vẫn hoạt động bình thường. Bấm thử lại, nếu
          vẫn lỗi thì tải lại trang.
        </p>
        <code className="eb-msg">{String(error?.message || error).slice(0, 200)}</code>
        <button type="button" className="btn btn-outline eb-retry" onClick={this.handleRetry}>
          <RefreshCw size={13} />
          <span>Thử lại</span>
        </button>

        <style>{`
          .eb-panel {
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 10px;
            border-color: rgba(244, 63, 94, 0.35);
          }
          .eb-head {
            display: flex;
            align-items: center;
            gap: 8px;
            font-family: var(--font-display);
            font-weight: 600;
            font-size: 14px;
            color: var(--color-sell);
          }
          .eb-desc {
            margin: 0;
            font-size: 12px;
            line-height: 1.5;
            color: var(--text-muted);
          }
          .eb-msg {
            font-size: 10px;
            line-height: 1.4;
            color: var(--text-muted);
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 8px;
            word-break: break-word;
          }
          .eb-retry {
            align-self: flex-start;
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 12px;
            padding: 7px 12px;
          }
        `}</style>
      </div>
    );
  }
}
