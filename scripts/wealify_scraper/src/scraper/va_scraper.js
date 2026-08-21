const config = require('../config');

async function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Đóng Drawer chi tiết Tài khoản quốc tế
 */
async function closeVaDrawer(page) {
  if (page.isClosed()) return;
  try {
    const closeBtn = await page.$('.ant-drawer-close, button[aria-label="Close"], button.close, [class*="close"]');
    if (closeBtn) {
      await closeBtn.click().catch(() => {});
    } else {
      await page.evaluate(() => {
        const mask = document.querySelector('.ant-drawer-mask, .drawer-mask');
        if (mask) mask.click();
      });
      await page.keyboard.press('Escape').catch(() => {});
    }

    await page.waitForFunction(() => {
      const openDrawer = document.querySelector('.ant-drawer-open');
      return !openDrawer;
    }, { timeout: 1200 }).catch(() => {});

    await delay(150);
  } catch (err) {}
}

/**
 * Điều hướng tới trang Tài khoản quốc tế (/va/list)
 */
async function navigateToVaPage(page) {
  if (page.isClosed()) return;
  console.log('[Navigation] Đang điều hướng tới trang Tài khoản quốc tế (/va/list)...');

  try {
    const clickedMenu = await page.evaluate(async () => {
      const elements = Array.from(document.querySelectorAll('div, li, span, a, p'));
      const viMenu = elements.find(el => el.innerText && el.innerText.trim() === 'Ví');
      if (viMenu) {
        viMenu.click();
        await new Promise(r => setTimeout(r, 400));
      }

      const subElements = Array.from(document.querySelectorAll('div, li, span, a, p'));
      const tkMenu = subElements.find(el => el.innerText && (el.innerText.includes('Tài khoản') || el.innerText.includes('Danh sách')));
      if (tkMenu) {
        tkMenu.click();
        return true;
      }
      return false;
    });

    if (clickedMenu) {
      console.log('✓ [Navigation] Đã click menu Ví > Tài khoản.');
      await delay(1500);
      return;
    }
  } catch (err) {}

  const currentUrl = page.url();
  if (!currentUrl.includes('/va/list') && !currentUrl.includes('/va')) {
    const targetUrl = config.baseUrl.replace(/\/$/, '') + '/va/list';
    console.log(`[Navigation] Truy cập trực tiếp URL: ${targetUrl}`);
    await page.goto(targetUrl, { waitUntil: 'networkidle2' }).catch(() => {});
  }
}

/**
 * Trích xuất danh sách Tài khoản quốc tế từ bảng dữ liệu (Bỏ qua thead)
 */
async function scrapeVaTableRows(page) {
  if (page.isClosed()) return [];

  return await page.evaluate(() => {
    const rows = [];
    // Chỉ chọn rows trong tbody, tuyệt đối không lấy thead
    const trElements = Array.from(document.querySelectorAll('tbody tr, .ant-table-tbody > tr.ant-table-row'));

    for (let i = 0; i < trElements.length; i++) {
      const tr = trElements[i];
      // Bỏ qua nếu là header hoặc hàng rỗng
      if (tr.closest('thead') || tr.classList.contains('ant-table-measure-row')) continue;

      const cells = Array.from(tr.querySelectorAll('td, [role="cell"], .ant-table-cell'));
      if (cells.length >= 5) {
        // Cột 0: Tên tài khoản (VD: "ETSY SELLER")
        const accountName = cells[0] ? cells[0].innerText.replace(/\n+/g, ' ').trim() : '';

        // Cột 1: Số tài khoản (VD: "9631249900000105835" hoặc "**************001")
        let accountNumber = '';
        if (cells[1]) {
          const rawAcc = cells[1].innerText.replace(/\n+/g, ' ').trim();
          accountNumber = rawAcc.replace(/[^\w*•]/g, '').trim() || rawAcc;
        }

        // Cột 2: Nguồn rút (VD: "Etsy", "Payoneer", "Paypal", "PingPong", "Amazon")
        const payoutSource = cells[2] ? cells[2].innerText.trim() : '';

        // Cột 3: Ngân hàng (VD: "BIDV", "MSB", "TCB")
        const bankName = cells[3] ? cells[3].innerText.replace(/👑|⭐/g, '').trim() : '';

        // Cột 4: Tổng số tiền nhận được (VD: "1,315,868,000", "26,405.19")
        const totalReceived = cells[4] ? cells[4].innerText.trim() : '0';

        // Cột 5: Đơn vị tiền tệ (VD: "VND", "USD")
        const currency = cells[5] ? cells[5].innerText.trim() : 'VND';

        // Cột 6: Trạng thái (VD: "Active", "Process", "Inactive")
        let status = 'Active';
        if (cells[6]) {
          const statusText = cells[6].innerText.trim();
          if (/Process|Đang xử lý/i.test(statusText)) status = 'Process';
          else if (/Inactive|Không hoạt động/i.test(statusText)) status = 'Inactive';
          else if (/Active|Hoạt động/i.test(statusText)) status = 'Active';
        }

        // Bỏ qua dòng header nếu bị lọt vào
        if (accountName === 'Tên tài khoản' || accountNumber === 'Số tài khoản') continue;

        rows.push({
          rowIndex: i,
          accountName: accountName,
          accountNumber: accountNumber,
          payoutSource: payoutSource,
          bankName: bankName,
          totalReceived: totalReceived,
          currency: currency,
          status: status
        });
      }
    }

    return rows;
  });
}

/**
 * Mở Drawer "Chi tiết tài khoản quốc tế" và bóc tách 100% dữ liệu
 */
async function scrapeVaDrawerDetail(page, rowIndex, expectedName, expectedAccNum) {
  if (page.isClosed()) return null;

  try {
    // 1. Đảm bảo drawer cũ đã đóng
    await closeVaDrawer(page);

    // 2. Lấy row handle trong tbody
    const rowHandles = await page.$$('tbody tr, .ant-table-tbody > tr.ant-table-row');
    const targetRow = rowHandles[rowIndex];
    if (!targetRow) return null;

    await targetRow.scrollIntoViewIfNeeded().catch(() => {});
    await delay(100);

    // 3. Click vào nút "Xem chi tiết" (Cột cuối cùng) hoặc click vào hàng
    const detailBtn = (await targetRow.$('a, button, span:has-text("Xem chi tiết"), td:last-child')) || targetRow;
    await detailBtn.click({ delay: 40 }).catch(() => targetRow.click({ delay: 40 }));

    // 4. Chờ Drawer "Chi tiết tài khoản quốc tế" xuất hiện
    await page.waitForFunction(() => {
      const text = document.body.innerText || '';
      return text.includes('Chi tiết tài khoản quốc tế') || 
             (text.includes('Tên tài khoản') && text.includes('Mã SWIFT')) ||
             (text.includes('Tên ngân hàng') && text.includes('Nguồn rút'));
    }, { timeout: 3500 }).catch(() => {});

    await delay(300);

    // 5. Bóc tách dữ liệu chính xác từ Drawer
    const vaDetailData = await page.evaluate((expName, expAccNum) => {
      const allDrawers = Array.from(document.querySelectorAll('.ant-drawer-content, .ant-drawer-body, [role="dialog"], aside, .drawer, div'));
      const drawerEl = allDrawers.find(el => {
        const t = el.innerText || '';
        return t.includes('Chi tiết tài khoản quốc tế') || (t.includes('Tên gợi nhớ tài khoản') && t.includes('Mã SWIFT'));
      }) || document.body;

      const rawText = (drawerEl.innerText || '').replace(/\u00a0/g, ' ');
      const details = {
        raw_text: rawText
      };

      function extractVal(labelRegex) {
        const lines = rawText.split('\n').map(l => l.trim()).filter(Boolean);
        for (let i = 0; i < lines.length; i++) {
          const line = lines[i];
          if (labelRegex.test(line)) {
            if (line.includes(':') && line.split(':').length > 1) {
              const v = line.split(':').slice(1).join(':').trim();
              if (v) return v;
            }
            if (i + 1 < lines.length) {
              const nextLine = lines[i + 1];
              if (!/:$/.test(nextLine) && nextLine.length > 0) {
                return nextLine;
              }
            }
          }
        }
        return '';
      }

      // 1. Trạng thái (Active / Process / Inactive)
      let status = 'Active';
      if (/Inactive|Không hoạt động/i.test(rawText)) status = 'Inactive';
      else if (/Process|Đang xử lý/i.test(rawText)) status = 'Process';
      else if (/Active|Hoạt động/i.test(rawText)) status = 'Active';
      details['status'] = status;

      // 2. Tên tài khoản
      details['account_name'] = extractVal(/^Tên tài khoản/i) || expName;

      // 3. Tên gợi nhớ tài khoản
      details['account_nickname'] = extractVal(/^Tên gợi nhớ tài khoản/i) || details['account_name'];

      // 4. Số tài khoản
      details['account_number'] = extractVal(/^Số tài khoản/i) || expAccNum;

      // 5. Tên ngân hàng đầy đủ
      details['bank_name_full'] = extractVal(/^Tên ngân hàng/i);

      // 6. Mã SWIFT
      details['swift_bic'] = extractVal(/^(?:Mã SWIFT|SWIFT)/i);

      // 7. Quản lý bởi
      details['managed_by'] = extractVal(/^Quản lý bởi/i) || 'Không có người quản lý';

      // 8. Nguồn rút
      details['payout_source'] = extractVal(/^Nguồn rút/i);

      // 9. Phí
      details['fee'] = extractVal(/^Phí/i) || '0%';

      // 10. Đơn vị tiền tệ
      details['currency'] = extractVal(/^Đơn vị tiền tệ/i);

      // 11. Tổng tiền được nhận
      details['total_received_detail'] = extractVal(/^Tổng tiền được nhận/i);

      // 12. Thời gian tạo (VD: "15/02/2026 | 3:00 PM")
      details['created_at_detail'] = extractVal(/^Thời gian tạo/i);

      return details;
    }, expectedName, expectedAccNum);

    // 6. Đóng Drawer
    await closeVaDrawer(page);

    return vaDetailData;
  } catch (err) {
    await closeVaDrawer(page);
    return null;
  }
}

module.exports = {
  navigateToVaPage,
  scrapeVaTableRows,
  scrapeVaDrawerDetail,
  closeVaDrawer
};
