import { VERDICT_CLASS, edgeText, fmtPrice, fmtValue } from './verdictScanUtils';

/** Một dòng kết luận trong danh sách quét. CSS nằm ở ROW_CSS, component cha nhúng một lần. */
export default function VerdictRow({ row, onSelect, showMeta = false }) {
  const meta = showMeta
    ? [row.exchange, row.industry || row.sector, row.value ? `GTGD ${fmtValue(row.value)}` : null]
        .filter(Boolean)
        .join(' · ')
    : '';
  return (
    <div className={`vs-row ${VERDICT_CLASS[row.verdict] || ''}`}>
      <button type="button" className="vs-sym" onClick={() => onSelect?.(row.symbol)} title="Xem từng tiêu chí">
        {row.symbol}
      </button>
      <div className="vs-main">
        <div className="vs-line">
          <span className="vs-label">{row.label}</span>
          {row.held ? <span className="vs-held">Đang giữ</span> : null}
          {row.price !== null && row.price !== undefined ? (
            <span className="vs-price">{fmtPrice(row.price)}</span>
          ) : null}
        </div>
        {meta ? <div className="vs-meta">{meta}</div> : null}
        <div className="vs-headline">{row.headline}</div>
        {row.verdict !== 'wait' ? (
          <div className={`vs-edge vs-edge-${row.edge || 'none'}`}>{edgeText(row)}</div>
        ) : null}
        {row.data_gaps?.length ? <div className="vs-gap">{row.data_gaps.join(' ')}</div> : null}
      </div>
    </div>
  );
}
