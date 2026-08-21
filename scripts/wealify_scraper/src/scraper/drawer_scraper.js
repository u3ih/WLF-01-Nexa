async function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Đóng Drawer / Sidebar hoàn toàn và chờ animation kết thúc
 */
async function closeSidebarDrawer(page) {
  if (page.isClosed()) return;
  try {
    // 1. Thử click nút đóng X bằng Puppeteer ElementHandle thật
    const closeBtn = await page.$('.ant-drawer-close, button[aria-label="Close"], button.close, [class*="close"]');
    if (closeBtn) {
      await closeBtn.click().catch(() => {});
    } else {
      // 2. Click backdrop hoặc phím Escape
      await page.evaluate(() => {
        const mask = document.querySelector('.ant-drawer-mask, .drawer-mask');
        if (mask) mask.click();
      });
      await page.keyboard.press('Escape').catch(() => {});
    }

    // Chờ drawer đóng hẳn
    await page.waitForFunction(() => {
      const openDrawer = document.querySelector('.ant-drawer-open');
      return !openDrawer;
    }, { timeout: 1200 }).catch(() => {});

    await delay(120);
  } catch (err) {}
}

/**
 * Điều hướng tới trang Giao dịch Thẻ ảo
 */
async function navigateToTransactionsPage(page) {
  if (page.isClosed()) return;
  console.log('[Navigation] Đang kiểm tra điều hướng tới trang Giao dịch Thẻ ảo...');

  try {
    const clickedMenu = await page.evaluate(async () => {
      const elements = Array.from(document.querySelectorAll('div, li, span, a, p'));
      const theAo = elements.find(el => el.innerText && el.innerText.trim() === 'Thẻ ảo');
      if (theAo) {
        theAo.click();
        await new Promise(r => setTimeout(r, 400));
      }

      const subElements = Array.from(document.querySelectorAll('div, li, span, a, p'));
      const giaoDich = subElements.find(el => el.innerText && el.innerText.trim() === 'Giao dịch');
      if (giaoDich) {
        giaoDich.click();
        return true;
      }
      return false;
    });

    if (clickedMenu) {
      console.log('✓ [Navigation] Đã click menu Thẻ ảo > Giao dịch.');
      await delay(1500);
      return;
    }
  } catch (err) {}

  const currentUrl = page.url();
  if (!currentUrl.includes('/transactions') && !currentUrl.includes('giao-dich')) {
    const targetUrl = 'https://app.wealify.com/vc/transactions';
    console.log(`[Navigation] Truy cập trực tiếp URL: ${targetUrl}`);
    await page.goto(targetUrl, { waitUntil: 'networkidle2' }).catch(() => {});
  }
}

/**
 * Trích xuất toàn bộ dữ liệu từ bảng giao dịch ở trang hiện tại
 */
async function scrapeTableRows(page) {
  if (page.isClosed()) return [];

  return await page.evaluate(() => {
    const rows = [];
    const trElements = Array.from(document.querySelectorAll('tbody tr, .ant-table-row, [role="row"]'));

    for (let i = 0; i < trElements.length; i++) {
      const tr = trElements[i];
      const cells = Array.from(tr.querySelectorAll('td, [role="cell"], .ant-table-cell'));
      
      if (cells.length >= 4) {
        const rowText = tr.innerText || '';
        const cellTexts = cells.map(c => c.innerText.trim());

        // Lấy mã giao dịch
        let txId = '';
        const txIdEl = tr.querySelector('a, code, .tx-id, span[class*="code"], span[class*="id"]');
        if (txIdEl) {
          txId = txIdEl.innerText.trim();
        } else {
          const match = rowText.match(/(?:TW\d+|WLF[\w-]+)/);
          if (match) txId = match[0];
        }

        // Lấy trạng thái
        let status = 'Success';
        const statusBadge = tr.querySelector('.ant-badge, .ant-tag, span[class*="status"], span[class*="badge"]');
        if (statusBadge) {
          status = statusBadge.innerText.trim();
        } else if (/Success|Thành công/i.test(rowText)) {
          status = 'Success';
        } else if (/Pending|Đang xử lý/i.test(rowText)) {
          status = 'Pending';
        } else if (/Failed|Thất bại|Declined/i.test(rowText)) {
          status = 'Failed';
        }

        rows.push({
          rowIndex: i,
          rawCells: cellTexts,
          detectedTxId: txId,
          status: status
        });
      }
    }

    return rows;
  });
}

/**
 * Mở Drawer/Sidebar cho 1 hàng và trích xuất TOÀN BỘ chi tiết
 * Sử dụng Puppeteer Native Click trực tiếp vào ElementHandle để kích hoạt React Event 100%
 */
async function scrapeRowSidebarDetail(page, rowIndex, detectedTxId) {
  if (page.isClosed()) return null;

  try {
    // 1. Đảm bảo drawer cũ đã đóng trước khi click dòng mới
    await closeSidebarDrawer(page);

    // 2. Lấy danh sách ElementHandle của các dòng trong bảng
    const rowHandles = await page.$$('tbody tr, .ant-table-row');
    const targetRow = rowHandles[rowIndex];
    if (!targetRow) return null;

    // Cuộn dòng vào giữa màn hình
    await targetRow.scrollIntoViewIfNeeded().catch(() => {});
    await delay(80);

    // 3. Click bằng Puppeteer Mouse Event thật
    // Ưu tiên click vào ô Mã giao dịch (td:nth-child(4) hoặc link bên trong), fallback vào cả row
    const txCell = (await targetRow.$('td:nth-child(4)')) || 
                   (await targetRow.$('td:nth-child(3)')) || 
                   (await targetRow.$('a')) || 
                   (await targetRow.$('span'));

    if (txCell) {
      await txCell.click({ delay: 30 }).catch(() => targetRow.click({ delay: 30 }));
    } else {
      await targetRow.click({ delay: 30 });
    }

    // 4. Đợi Sidebar xuất hiện và có nội dung
    const isSidebarVisible = await page.waitForFunction(() => {
      const allElements = Array.from(document.querySelectorAll('div, aside, section, [role="dialog"]'));
      const sidebar = allElements.find(el => (el.innerText || '').includes('Chi tiết giao dịch'));
      return !!sidebar;
    }, { timeout: 3000 }).then(() => true).catch(() => false);

    if (!isSidebarVisible) {
      // Thử click lại trực tiếp vào targetRow nếu lần 1 chưa ăn
      await targetRow.click({ delay: 50 }).catch(() => {});
      await delay(400);
    }

    // 5. Trích xuất chi tiết theo cấu trúc chính xác của Wealify
    const sidebarData = await page.evaluate((expectedTxId) => {
      const allElements = Array.from(document.querySelectorAll('div, aside, section, [role="dialog"]'));
      let sidebarEl = allElements.find(el => {
        const text = el.innerText || '';
        return text.includes('Chi tiết giao dịch') && 
               (text.includes('Loại giao dịch') || text.includes('Thời gian tạo') || text.includes('Thành công vào') || text.includes('Số tiền'));
      });

      if (!sidebarEl) {
        sidebarEl = document.querySelector('.ant-drawer-content, [role="dialog"], aside, .drawer, [class*="drawer"]');
      }

      if (!sidebarEl) return null;

      const rawText = sidebarEl.innerText || '';
      const cleanRaw = rawText.replace(/\u00a0/g, ' ');

      const details = {
        raw_text: cleanRaw
      };

      // Helper lấy text theo nhãn
      function extractField(labelRegex) {
        const lines = cleanRaw.split('\n').map(l => l.trim()).filter(Boolean);
        for (let i = 0; i < lines.length; i++) {
          const line = lines[i];
          if (labelRegex.test(line)) {
            if (line.includes(':') && line.split(':').length > 1) {
              const val = line.split(':').slice(1).join(':').trim();
              if (val) return val;
            }
            if (i + 1 < lines.length) {
              const nextLine = lines[i + 1];
              if (!/:$/.test(nextLine) && nextLine.length > 0) {
                return nextLine;
              }
            }
          }
        }
        return null;
      }

      // 1. Loại giao dịch
      details['transaction_type'] = extractField(/^Loại giao dịch/i);

      // 2. Tham chiếu
      details['reference'] = extractField(/^Tham chiếu/i);

      // 3. ID giao dịch chính
      details['transaction_id'] = extractField(/^(?:ID|Mã) giao dịch(?: nạp vào ví| chi tiêu| rút tiền)?/i) || expectedTxId;

      // 4. ID giao dịch liên kết
      details['linked_transaction_id'] = extractField(/^(?:ID|Mã) giao dịch (?:rút về thẻ|nạp vào ví|liên kết|nguồn)/i);

      // 5. Tên thẻ
      details['card_name'] = extractField(/^Tên thẻ/i);

      // 6. Số thẻ
      details['card_number'] = extractField(/^Số thẻ/i);

      // 7. Số tiền của bạn
      details['user_amount'] = extractField(/^Số tiền của bạn/i);

      // 8. Số tiền nạp / chi tiêu / thực tế
      details['settled_amount'] = extractField(/^Số tiền (?:nạp|chi tiêu|rút|thực tế|giao dịch)/i);

      // 9. Tỷ giá
      details['exchange_rate'] = extractField(/^Tỷ giá/i);

      // 10. Trạng thái
      details['status'] = extractField(/^Trạng thái/i);

      // 11. Thời gian tạo
      details['created_at_detail'] = extractField(/^Thời gian tạo/i);

      // 12. Thành công vào / Thời gian hoàn tất
      details['completed_at'] = extractField(/^(?:Thành công vào|Thời gian hoàn tất|Hoàn thành vào)/i);

      // 13. Phí giao dịch (nếu có)
      details['fee'] = extractField(/^(?:Phí giao dịch|Phí xử lý|Phí dịch vụ|Phí)/i);

      // 14. Đơn vị chấp nhận / Merchant (nếu có)
      details['merchant'] = extractField(/^(?:Đơn vị chấp nhận|Merchant|Cửa hàng)/i);

      // 15. Mã MCC (nếu có)
      details['mcc'] = extractField(/^(?:Mã MCC|MCC|Ngành hàng)/i);

      // 16. Mã tham chiếu cổng (nếu có)
      details['gateway_ref'] = extractField(/^(?:Mã tham chiếu|Gateway Reference|Trace ID|ARN)/i);

      return details;
    }, detectedTxId);

    // 6. Đóng sidebar ngay sau khi lấy xong
    await closeSidebarDrawer(page);

    return sidebarData;
  } catch (err) {
    await closeSidebarDrawer(page);
    return null;
  }
}

module.exports = {
  navigateToTransactionsPage,
  scrapeTableRows,
  scrapeRowSidebarDetail,
  closeSidebarDrawer
};
