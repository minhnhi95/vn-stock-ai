// Dùng chung cho panel "Kết luận cả rổ" và modal "Tìm mã đáng mua".

export const VERDICT_CLASS = { buy_consider: 'vs-buy', wait: 'vs-wait', avoid: 'vs-avoid' };

// Với "Chờ thêm" không có đúng/sai (không ngụ ý hướng giá) nên không hiện dòng này.
export const EDGE_TEXT = {
  better: 'Quá khứ với mã này: tốt hơn chọn bừa',
  same: 'Quá khứ với mã này: ngang chọn bừa',
  worse: 'Quá khứ với mã này: kém hơn chọn bừa',
};

const hasNum = (v) => v !== null && v !== undefined && !Number.isNaN(Number(v));

export const fmtPrice = (v) => (hasNum(v) ? `${Math.round(v).toLocaleString('vi-VN')} đ` : '');

export const fmtValue = (v) => {
  if (!hasNum(v)) return '';
  const ty = Number(v) / 1e9;
  return `${ty.toLocaleString('vi-VN', { maximumFractionDigits: ty >= 10 ? 0 : 1 })} tỷ`;
};

export const fmtPct = (v) => (hasNum(v) ? `${Math.round(Number(v) * 100)}%` : '');

export const fmtDay = (iso) => {
  if (!iso) return '';
  const [y, m, d] = String(iso).split('-');
  return d && m ? `${d}/${m}/${y}` : iso;
};

export const edgeText = (row) => {
  const base = EDGE_TEXT[row.edge];
  if (!base) return 'Chưa đủ dữ liệu quá khứ để đo';
  if (!hasNum(row.hit_ratio) || !hasNum(row.baseline_hit_ratio)) return base;
  return `${base} (đúng ${fmtPct(row.hit_ratio)}, chọn bừa ${fmtPct(row.baseline_hit_ratio)})`;
};

/** Phạm vi lượt quét, để tiêu đề nói đúng sàn đã tìm thay vì ghi cứng. */
export const scopeLabel = (c) => {
  if (!c) return 'cổ phiếu';
  if (c.mode === 'vn100') return 'rổ VN100';
  if (c.exchanges?.length) return `sàn ${c.exchanges.join(' + ')}`;
  return 'toàn thị trường';
};

/** Một câu cho biết lượt quét phủ tới đâu — để "không có mã X" không bị hiểu nhầm là "X không đáng mua". */
export const coverageText = (c) => {
  if (!c) return '';
  if (c.mode === 'vn100') return 'Lượt này chỉ chấm VN100 và mã bạn đang giữ hoặc đặt cảnh báo.';
  if (c.mode !== 'market') return '';
  if (!c.board_ok) {
    return `Không lấy được bảng giá ${scopeLabel(c)}, nên lượt này chỉ chấm VN100 và mã bạn đang giữ hoặc đặt cảnh báo.`;
  }
  const reasons = [
    c.no_trade ? `${c.no_trade} mã không khớp lệnh` : null,
    c.penny ? `${c.penny} mã giá dưới ${fmtPrice(c.min_price)}` : null,
    c.illiquid ? `${c.illiquid} mã giao dịch dưới ${fmtValue(c.min_value)} ở phiên gần nhất` : null,
    c.no_data || c.board_failed ? `${(c.no_data || 0) + (c.board_failed || 0)} mã không có bảng giá` : null,
  ].filter(Boolean);
  return (
    `Lọc ${c.listed} cổ phiếu trên ${scopeLabel(c)}: chấm ${c.priority} mã luôn được chấm (VN100, mã đang giữ, ` +
    `mã đặt cảnh báo) và ${c.prefilter_passed} mã khác đủ thanh khoản. ` +
    (reasons.length
      ? `Loại ${c.excluded} mã ở vòng lọc (${reasons.join(', ')}) — những mã này đằng nào cũng trượt bộ lọc an toàn.`
      : '')
  );
};

export const ROW_CSS = `
  .vs-row {
    display: grid;
    grid-template-columns: 52px 1fr;
    gap: 8px;
    padding: 8px 10px;
    border: 1px solid var(--border-color);
    border-left-width: 3px;
    border-radius: 7px;
    background: rgba(0, 0, 0, 0.2);
  }
  .vs-row.vs-buy { border-left-color: var(--color-buy); }
  .vs-row.vs-wait { border-left-color: var(--color-hold, #f59e0b); }
  .vs-row.vs-avoid { border-left-color: var(--color-sell); }
  .vs-sym {
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    font-family: var(--font-display);
    font-weight: 700;
    font-size: 13px;
    color: var(--text-primary);
    text-align: left;
    align-self: start;
  }
  .vs-sym:hover { color: var(--accent-primary, #38bdf8); text-decoration: underline; }
  .vs-main { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
  .vs-line { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 11.5px; }
  .vs-label { font-weight: 600; }
  .vs-buy .vs-label, span.vs-buy { color: var(--color-buy); }
  .vs-wait .vs-label, span.vs-wait { color: var(--color-hold, #f59e0b); }
  .vs-avoid .vs-label, span.vs-avoid { color: var(--color-sell); }
  .vs-price {
    margin-left: auto;
    font-variant-numeric: tabular-nums;
    color: var(--text-muted);
    font-size: 11px;
  }
  .vs-held {
    font-size: 9.5px;
    padding: 1px 6px;
    border-radius: 999px;
    background: rgba(56, 189, 248, 0.15);
    color: var(--accent-primary, #38bdf8);
  }
  .vs-meta { font-size: 10px; color: var(--text-muted); }
  .vs-headline { font-size: 11px; line-height: 1.5; color: var(--text-secondary); }
  .vs-edge { font-size: 10px; color: var(--text-muted); }
  .vs-edge-better { color: var(--color-buy); }
  .vs-edge-worse { color: var(--color-sell); }
  .vs-gap { font-size: 10px; color: var(--color-hold, #f59e0b); }
`;
