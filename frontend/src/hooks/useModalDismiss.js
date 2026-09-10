import { useEffect } from 'react';

/**
 * Đóng modal bằng phím Escape + khoá cuộn nền khi modal đang mở.
 *
 * Các modal (Lọc an toàn, Review danh mục) trước đây chỉ đóng được bằng
 * cách bấm nút × hoặc click nền — không phím tắt, và trang phía sau vẫn cuộn
 * được nên trên mobile rất dễ lạc vị trí sau khi đóng.
 */
export default function useModalDismiss(open, onClose) {
  useEffect(() => {
    if (!open) return undefined;

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose?.();
      }
    };

    document.addEventListener('keydown', onKeyDown);

    // Khoá cuộn nền, nhớ lại giá trị cũ để không đè style của người khác.
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [open, onClose]);
}
