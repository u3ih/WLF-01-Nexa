const config = require('../config');

async function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Đóng Drawer Thẻ hoàn toàn
 */
async function closeCardDrawer(page) {
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
 * Điều hướng tới trang Danh sách thẻ ảo
 */
async function navigateToCardsPage(page) {
  if (page.isClosed()) return;
  console.log('[Navigation] Đang điều hướng tới trang Danh sách thẻ ảo...');

  try {
    const clickedMenu = await page.evaluate(async () => {
      const elements = Array.from(document.querySelectorAll('div, li, span, a, p'));
      const theAo = elements.find(el => el.innerText && el.innerText.trim() === 'Thẻ ảo');
      if (theAo) {
        theAo.click();
        await new Promise(r => setTimeout(r, 400));
      }

      const subElements = Array.from(document.querySelectorAll('div, li, span, a, p'));
      const danhSach = subElements.find(el => el.innerText && el.innerText.trim() === 'Danh sách');
      if (danhSach) {
        danhSach.click();
        return true;
      }
      return false;
    });

    if (clickedMenu) {
      console.log('✓ [Navigation] Đã click menu Thẻ ảo > Danh sách.');
      await delay(1500);
      return;
    }
  } catch (err) {}

  const currentUrl = page.url();
  if (!currentUrl.includes('/vc/list') && !currentUrl.includes('/list')) {
    const targetUrl = config.baseUrl.replace(/\/$/, '') + '/vc/list';
    console.log(`[Navigation] Truy cập trực tiếp URL: ${targetUrl}`);
    await page.goto(targetUrl, { waitUntil: 'networkidle2' }).catch(() => {});
  }
}

/**
 * Trích xuất danh sách thẻ từ bảng dữ liệu bằng nhận diện thông minh từng ô
 */
async function scrapeCardTableRows(page) {
  if (page.isClosed()) return [];

  return await page.evaluate(() => {
    const rows = [];
    const trElements = Array.from(document.querySelectorAll('tbody tr, .ant-table-row, [role="row"]'));

    for (let i = 0; i < trElements.length; i++) {
      const tr = trElements[i];
      const cells = Array.from(tr.querySelectorAll('td, [role="cell"], .ant-table-cell'));

      if (cells.length >= 3) {
        let cardName = '';
        let last4 = '';
        let purpose = '';
        let balance = '$0.00';
        let totalDeposit = '$0.00';
        let totalWithdrawal = '$0.00';
        let createdAt = '';

        for (let cIdx = 0; cIdx < cells.length; cIdx++) {
          const t = cells[cIdx].innerText.trim();
          if (!t) continue;

          // Ô nạp: có dấu +
          if (/^\+[\$₫]/.test(t) || /^\+\s*\d/.test(t)) {
            totalDeposit = t;
          } 
          // Ô rút: có dấu -
          else if (/^-[\$₫]/.test(t) || /^-\s*\d/.test(t)) {
            totalWithdrawal = t;
          } 
          // Ô số dư thẻ: có $ nhưng không có dấu +/-
          else if (/^[\$₫]\s*[\d,.]+/.test(t) || /^[\d,.]+\s*(?:USD|VND)/i.test(t)) {
            balance = t;
          } 
          // Ô thời gian tạo: dạng ngày dd/mm/yyyy
          else if (/\d{1,2}\/\d{1,2}\/\d{4}/.test(t)) {
            createdAt = t;
          } 
          // Ô chứa tên thẻ và số thẻ (xxxx xxxx xxxx 0003)
          else if (t.includes('xxxx') || t.includes('****') || (t.split('\n').length > 1 && !cardName)) {
            const lines = t.split('\n').map(s => s.trim()).filter(Boolean);
            cardName = lines[0];
            const m = t.match(/(?:[x*]{4}\s*){1,3}(\d{4})/i) || t.match(/\d{4}$/);
            if (m) last4 = m[1] || m[0];
          } 
          // Ô mục đích thẻ
          else if (!purpose && t.length > 0 && !t.includes('$') && !t.includes('xxxx')) {
            purpose = t;
          }
        }

        const rowText = tr.innerText || '';
        let status = 'Active';
        if (/Inactive|Không hoạt động|Frozen|Đóng băng/i.test(rowText)) {
          status = 'Inactive';
        } else if (/Cancelled|Đã hủy/i.test(rowText)) {
          status = 'Cancelled';
        }

        rows.push({
          rowIndex: i,
          cardName: cardName,
          last4: last4,
          purpose: purpose,
          balance: balance,
          totalDeposit: totalDeposit,
          totalWithdrawal: totalWithdrawal,
          createdAt: createdAt,
          status: status
        });
      }
    }

    return rows;
  });
}

/**
 * Mở Drawer chi tiết Thẻ và bóc tách toàn bộ thông tin
 */
async function scrapeCardDrawerDetail(page, rowIndex, expectedCardName, expectedLast4) {
  if (page.isClosed()) return null;

  try {
    // 1. Đảm bảo drawer cũ đã đóng
    await closeCardDrawer(page);

    // 2. Lấy row handle
    const rowHandles = await page.$$('tbody tr, .ant-table-row');
    const targetRow = rowHandles[rowIndex];
    if (!targetRow) return null;

    await targetRow.scrollIntoViewIfNeeded().catch(() => {});
    await delay(100);

    // 3. Kích hoạt click mở chi tiết bằng cả JS Dispatch Event và Puppeteer Mouse Click
    await page.evaluate((idx) => {
      const rows = Array.from(document.querySelectorAll('tbody tr, .ant-table-row'));
      const row = rows[idx];
      if (row) {
        row.scrollIntoView({ behavior: 'instant', block: 'center' });
        row.click();
        const firstCell = row.querySelector('td:nth-child(1), td:nth-child(2), div, span');
        if (firstCell) firstCell.click();
      }
    }, rowIndex);

    const box = await targetRow.boundingBox();
    if (box) {
      await page.mouse.click(box.x + Math.min(box.width / 4, 150), box.y + box.height / 2).catch(() => {});
    }

    // 4. Chờ Drawer chi tiết thẻ xuất hiện
    await page.waitForFunction(() => {
      const text = document.body.innerText || '';
      return text.includes('Biệt danh thẻ') || text.includes('Số điện thoại') || text.includes('Ngày hết hạn');
    }, { timeout: 3500 }).catch(() => {});

    await delay(300);

    // 5. Bóc tách dữ liệu từ Sidebar Drawer
    const cardDetailData = await page.evaluate((expName, expLast4) => {
      // Tìm container chứa Sidebar Drawer
      const allDrawers = Array.from(document.querySelectorAll('.ant-drawer-content, .ant-drawer-body, [role="dialog"], aside, .drawer, div'));
      const drawerEl = allDrawers.find(el => {
        const t = el.innerText || '';
        return t.includes('Biệt danh thẻ') && (t.includes('Số điện thoại') || t.includes('Ngày hết hạn') || t.includes('Số dư thẻ'));
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

      // 1. Biệt danh thẻ (VD: "Volcano EU", "Zenith Main")
      details['nickname'] = extractVal(/^Biệt danh thẻ/i) || expName;

      // 2. Email (VD: "wealifytester@yopmail.com")
      details['email'] = extractVal(/^Email/i);

      // 3. Số điện thoại (VD: "912345678")
      details['phone'] = extractVal(/^Số điện thoại/i);

      // 4. Số thẻ hiển thị trong drawer (VD: "**** **** **** 0004")
      details['card_number_masked'] = extractVal(/^Số thẻ/i) || `**** **** **** ${expLast4}`;

      // 5. CVV (VD: "***")
      details['cvv'] = extractVal(/^CVV/i) || '***';

      // 6. Ngày hết hạn (VD: "12/29")
      details['expiry_date'] = extractVal(/^Ngày hết hạn/i);

      // 7. Số dư thẻ (VD: "116.86 USD")
      details['balance_detail'] = extractVal(/^Số dư thẻ/i);

      // 8. Badge trạng thái
      let badgeStatus = 'Active';
      if (/Active|Hoạt động/i.test(rawText)) badgeStatus = 'Active';
      else if (/Frozen|Đóng băng/i.test(rawText)) badgeStatus = 'Frozen';
      else if (/Cancelled|Đã hủy/i.test(rawText)) badgeStatus = 'Cancelled';
      details['badge_status'] = badgeStatus;

      // 9. Loại thẻ
      let network = 'VISA Platinum Business';
      if (/VISA/i.test(rawText)) network = 'VISA Platinum Business';
      else if (/Mastercard/i.test(rawText)) network = 'Mastercard Business';
      details['card_network'] = network;

      return details;
    }, expectedCardName, expectedLast4);

    // 6. Đóng Drawer
    await closeCardDrawer(page);

    return cardDetailData;
  } catch (err) {
    await closeCardDrawer(page);
    return null;
  }
}

module.exports = {
  navigateToCardsPage,
  scrapeCardTableRows,
  scrapeCardDrawerDetail,
  closeCardDrawer
};
