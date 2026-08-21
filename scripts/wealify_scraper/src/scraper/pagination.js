async function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Áp dụng bộ lọc ngày nếu có cấu hình
 */
async function applyDateFilter(page, dateFrom, dateTo) {
  if (!dateFrom && !dateTo) return;

  console.log(`[Filter] Áp dụng lọc ngày từ ${dateFrom || 'bắt đầu'} đến ${dateTo || 'nay'}...`);

  try {
    const inputs = await page.$$('input[placeholder*="dd/mm/yyyy"], input[placeholder*="ngày"], input.ant-picker-input');
    if (inputs.length >= 2) {
      if (dateFrom) {
        await inputs[0].click();
        await page.keyboard.down('Meta');
        await page.keyboard.press('KeyA');
        await page.keyboard.up('Meta');
        await page.keyboard.type(dateFrom);
        await page.keyboard.press('Enter');
        await delay(500);
      }
      if (dateTo) {
        await inputs[1].click();
        await page.keyboard.down('Meta');
        await page.keyboard.press('KeyA');
        await page.keyboard.up('Meta');
        await page.keyboard.type(dateTo);
        await page.keyboard.press('Enter');
        await delay(500);
      }
    }
  } catch (err) {
    console.warn('[Filter] Không thể nhập bộ lọc ngày:', err.message);
  }
}

/**
 * Kiểm tra và chuyển sang trang kế tiếp
 * Chỉ click nếu thực sự có phân trang của bảng dữ liệu và nút Next chưa bị disabled
 */
async function goToNextPage(page) {
  if (page.isClosed()) return false;

  try {
    const paginationState = await page.evaluate(() => {
      // 1. Tìm vùng phân trang Ant Design hoặc bảng dữ liệu
      const paginationContainer = document.querySelector('.ant-table-pagination, .ant-pagination, ul.pagination');
      if (!paginationContainer) {
        return { hasNext: false, reason: 'Không có component phân trang' };
      }

      // Kiểm tra nút Next cụ thể trong container phân trang
      const nextBtn = paginationContainer.querySelector('.ant-pagination-next:not(.ant-pagination-disabled) button, .ant-pagination-next:not(.ant-pagination-disabled) a, .ant-pagination-next:not([aria-disabled="true"])');
      
      if (!nextBtn) {
        return { hasNext: false, reason: 'Nút Next bị disabled hoặc là trang cuối' };
      }

      // Lấy số trang hiện tại để đối chiếu
      const activeItem = paginationContainer.querySelector('.ant-pagination-item-active');
      const currentPageNum = activeItem ? activeItem.innerText.trim() : null;

      // Click nút Next
      nextBtn.click();

      return {
        hasNext: true,
        previousPageNum: currentPageNum
      };
    });

    if (!paginationState.hasNext) {
      return false;
    }

    console.log('[Pagination] Đang chuyển sang trang tiếp theo...');
    await delay(1200);

    // Chờ loading của bảng biến mất
    await page.waitForSelector('.ant-spin-spinning, .ant-table-placeholder', { hidden: true, timeout: 4000 }).catch(() => {});

    return true;
  } catch (err) {
    return false;
  }
}

module.exports = {
  applyDateFilter,
  goToNextPage
};
