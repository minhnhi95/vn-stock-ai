import { useState } from 'react';
import { FileText, AlertTriangle, ArrowUp, ArrowDown, Minus } from 'lucide-react';

/**
 * Chỉ số cơ bản, đọc được cho người chưa từng học tài chính.
 *
 * Bản cũ chấm màu theo ngưỡng cứng ("P/E < 10: rẻ") — đó là một phán quyết đội
 * lốt chú thích: 10 là rẻ với ngân hàng nhưng đắt với thép, và người mới không
 * có cách nào biết điều đó. Bản này bỏ hết ngưỡng đoán mò, thay bằng ba thứ
 * backend tính được thật:
 *   - một câu tiếng Việt nói con số đó nghĩa gì với tiền của người dùng
 *   - trung vị cùng ngành, kèm số mã đã dùng để tính
 *   - trường hợp con số này đánh lừa
 *
 * Chip so sánh cố ý KHÔNG tô xanh/đỏ. "Rẻ hơn ngành" tô xanh là gợi ý mua, mà
 * rẻ hơn ngành có thể chỉ vì thị trường đã biết một tin xấu mà người đọc chưa biết.
 */

const COMPARISON_ICON = {
  above: ArrowUp,
  below: ArrowDown,
  inline: Minus,
};

function MetricRow({ item, open, onToggle, showChip }) {
  const Icon = COMPARISON_ICON[item.comparison];
  return (
    <div className={`fm-row ${open ? 'open' : ''} ${showChip ? '' : 'no-chip'}`}>
      <button type="button" className="fm-head" onClick={onToggle} aria-expanded={open}>
        <span className="fm-label">{item.label}</span>
        <span className="fm-value">{item.display}</span>
        {/* Cột chip chỉ tồn tại khi mã này có bảng ngành. Không có thì bỏ hẳn cột,
            đừng để 13 ô rỗng chiếm chỗ trong một cột vốn đã hẹp. */}
        {showChip ? (
          <span className="fm-chip" title={item.comparison_text || undefined}>
            {Icon ? <Icon size={11} /> : null}
            {item.sector ? item.sector.display : null}
          </span>
        ) : null}
      </button>

      {open ? (
        <div className="fm-detail">
          <p className="fm-plain">{item.plain}</p>
          {item.comparison_text ? (
            <p className="fm-compare">
              {item.comparison_text}{' '}
              {/* Số mã dùng để tính là căn cứ để người đọc tự cân nhắc mức độ tin
                  cậy — 12 mã khác hẳn 5 mã. Viết thành câu riêng vì câu so sánh
                  đã kết thúc bằng một ngoặc đơn rồi. */}
              <span className="fm-sample">
                Trung vị của {item.sector.sample} mã cùng ngành.
              </span>
            </p>
          ) : null}
          <p className="fm-caveat">
            <AlertTriangle size={11} />
            <span>{item.caveat}</span>
          </p>
        </div>
      ) : null}
    </div>
  );
}

export default function Fundamentals({ data, symbol }) {
  const [openKey, setOpenKey] = useState(null);

  const available = data?.available;
  const items = data?.explain?.items || [];
  const sector = data?.explain?.sector;
  const benchmarkDate = data?.explain?.benchmark_date;
  const hasSector = items.some((i) => i.sector);

  return (
    <div className="glass-panel">
      <div className="panel-header">
        <div className="panel-title">
          <FileText size={16} className="text-accent" />
          <span>Cơ bản doanh nghiệp: {symbol}</span>
        </div>
        {data?.source ? <span className="fm-source">Nguồn: {data.source}</span> : null}
      </div>

      <div className="panel-content fm-content">
        {!available ? (
          <div className="fm-empty">{data?.reason || 'Đang tải dữ liệu cơ bản...'}</div>
        ) : (
          <>
            <p className="fm-intro">
              Bấm vào từng dòng để xem con số đó nghĩa là gì.
              {sector ? (
                <>
                  {' '}
                  So sánh với ngành <b>{sector}</b>
                  {benchmarkDate ? ` (số liệu ${benchmarkDate})` : null}.
                </>
              ) : (
                ' Mã này chưa có bảng trung vị ngành để đối chiếu.'
              )}
            </p>

            {items.length ? (
              <div className="fm-list">
                {items.map((item) => (
                  <MetricRow
                    key={item.key}
                    item={item}
                    showChip={hasSector}
                    open={openKey === item.key}
                    onToggle={() => setOpenKey(openKey === item.key ? null : item.key)}
                  />
                ))}
              </div>
            ) : (
              <div className="fm-empty">Không có chỉ số nào đọc được cho mã này.</div>
            )}

            {data.stale ? (
              <div className="fm-stale">
                <AlertTriangle size={12} />
                <span>
                  {data.stale_note ||
                    'Số liệu cơ bản đã cũ — không dùng để kết luận định giá hiện tại.'}
                </span>
              </div>
            ) : null}
            {data.period ? <div className="fm-period">Kỳ báo cáo: {data.period}</div> : null}
          </>
        )}
      </div>

      <style>{`
        .fm-content { gap: 10px; }
        .fm-source { font-size: 10px; color: var(--text-muted); }
        .fm-empty {
          padding: 20px 10px;
          text-align: center;
          color: var(--text-muted);
          font-size: 12px;
        }
        .fm-intro {
          margin: 0;
          font-size: 11px;
          line-height: 1.6;
          color: var(--text-muted);
        }
        .fm-intro b { color: var(--text-primary); }
        .fm-list { display: flex; flex-direction: column; gap: 4px; }
        .fm-row {
          border: 1px solid var(--border-color);
          border-radius: 7px;
          background: rgba(0, 0, 0, 0.2);
          overflow: hidden;
        }
        .fm-row.open { border-color: var(--color-accent); }
        .fm-head {
          width: 100%;
          display: grid;
          grid-template-columns: 1fr auto auto;
          align-items: center;
          gap: 8px;
          padding: 8px 10px;
          background: none;
          border: none;
          color: inherit;
          text-align: left;
          cursor: pointer;
          font-size: 11px;
        }
        .fm-label { color: var(--text-primary); }
        .fm-value {
          font-family: var(--font-display);
          font-weight: 700;
          font-size: 13px;
          color: var(--text-primary);
          font-variant-numeric: tabular-nums;
          white-space: nowrap;
        }
        /* Chip trung tính: nói cao hay thấp so với ngành, không nói tốt hay xấu. */
        .fm-chip {
          display: inline-flex;
          align-items: center;
          gap: 3px;
          min-width: 62px;
          justify-content: flex-end;
          font-size: 10px;
          color: var(--text-muted);
          font-variant-numeric: tabular-nums;
          white-space: nowrap;
        }
        .fm-row.no-chip .fm-head { grid-template-columns: 1fr auto; }
        .fm-detail {
          padding: 0 10px 10px;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .fm-plain {
          margin: 0;
          font-size: 11.5px;
          line-height: 1.65;
          color: var(--text-primary);
        }
        .fm-compare {
          margin: 0;
          font-size: 11px;
          line-height: 1.6;
          color: var(--color-accent);
        }
        .fm-sample { color: var(--text-muted); }
        .fm-caveat {
          margin: 0;
          display: flex;
          gap: 6px;
          font-size: 10.5px;
          line-height: 1.6;
          color: var(--text-muted);
        }
        .fm-caveat svg { flex: 0 0 auto; margin-top: 3px; }
        .fm-stale {
          display: flex;
          align-items: flex-start;
          gap: 6px;
          font-size: 10.5px;
          line-height: 1.5;
          color: var(--color-sell);
          background: rgba(244, 63, 94, 0.08);
          border: 1px solid rgba(244, 63, 94, 0.25);
          border-radius: 7px;
          padding: 8px 10px;
        }
        .fm-stale svg { flex: 0 0 auto; margin-top: 2px; }
        .fm-period { font-size: 10px; color: var(--text-muted); text-align: right; }
      `}</style>
    </div>
  );
}
