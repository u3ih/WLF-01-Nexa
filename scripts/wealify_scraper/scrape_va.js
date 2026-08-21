const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
puppeteer.use(StealthPlugin());

const path = require('path');
const fs = require('fs');
const config = require('./src/config');
const { performLogin } = require('./src/auth/login');
const NetworkInterceptor = require('./src/scraper/interceptor');
const {
  navigateToVaPage,
  scrapeVaTableRows,
  scrapeVaDrawerDetail,
  closeVaDrawer
} = require('./src/scraper/va_scraper');
const { goToNextPage } = require('./src/scraper/pagination');
const { normalizeVaRecord } = require('./src/parser/va_normalizer');
const {
  exportVaToJson,
  exportVaToCsv,
  generateVaSummaryReport
} = require('./src/storage/va_exporter');

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function main() {
  console.log('========================================================================');
  console.log('         WEALIFY VIRTUAL ACCOUNTS & DETAILS CRAWLER');
  console.log('========================================================================');
  console.log(`  Mục tiêu URL        : ${config.baseUrl}/va/list`);
  console.log(`  Tài khoản           : ${config.username || '(Nhập khi chạy)'}`);
  console.log(`  Chế độ Headless     : ${config.headless ? 'Bật (Ẩn cửa sổ)' : 'Tắt (Hiện trình duyệt)'}`);
  console.log(`  Cào chi tiết Sidebar: ${config.fullDrawer ? 'Bật' : 'Tắt'}`);
  console.log(`  Thư mục xuất file   : ${config.outputDir}`);
  console.log('========================================================================\n');

  console.log('[1/4] Khởi động trình duyệt Chromium Stealth...');
  const browser = await puppeteer.launch({
    headless: config.headless,
    defaultViewport: null,
    args: [
      '--start-maximized',
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-blink-features=AutomationControlled'
    ]
  });

  const allAccounts = [];
  const processedVaKeys = new Set();

  try {
    const page = await browser.newPage();
    await page.setUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36');
    await page.setViewport({ width: 1440, height: 900 });

    const interceptor = new NetworkInterceptor();
    interceptor.setup(page);

    // [2/4] Đăng nhập & Xác thực
    console.log('\n[2/4] Tiến hành đăng nhập và xác thực...');
    await performLogin(page);

    // [3/4] Điều hướng tới Danh sách Virtual Account
    console.log('\n[3/4] Điều hướng tới mục Danh sách Virtual Account (/va/list)...');
    await navigateToVaPage(page);
    await delay(3000);

    // [4/4] Cào dữ liệu VA và chi tiết Drawer
    console.log('\n[4/4] Bắt đầu cào danh sách Virtual Account và chi tiết Drawer...');
    let currentPage = 1;

    while (true) {
      console.log(`\n🏦 Đang xử lý Trang VA #${currentPage}...`);
      await delay(1000);

      const vaRows = await scrapeVaTableRows(page);
      console.log(`  ✓ Tìm thấy ${vaRows.length} tài khoản trên giao diện.`);

      if (vaRows.length === 0) {
        console.log('[Info] Không có tài khoản nào trên trang này.');
        break;
      }

      for (let i = 0; i < vaRows.length; i++) {
        const rawRow = vaRows[i];
        const vaKey = rawRow.vaId || rawRow.accountNumber || rawRow.accountName || `VA_${i}`;

        if (processedVaKeys.has(vaKey)) {
          continue;
        }

        let vaDetail = null;
        if (config.fullDrawer) {
          process.stdout.write(`  [${i + 1}/${vaRows.length}] Mở chi tiết: ${rawRow.accountName} (${rawRow.accountNumber}) ... `);
          vaDetail = await scrapeVaDrawerDetail(page, i, rawRow.accountName, rawRow.accountNumber);
          console.log(vaDetail ? '✓ (Thành công)' : '⚠️ (Lấy dữ liệu bảng)');
        }

        const normalized = normalizeVaRecord(rawRow, vaDetail);
        allAccounts.push(normalized);
        processedVaKeys.add(vaKey);
      }

      await closeVaDrawer(page);

      if (config.pageLimit > 0 && currentPage >= config.pageLimit) {
        break;
      }

      const hasNext = await goToNextPage(page);
      if (!hasNext) {
        console.log('\n✓ Đã quét hết toàn bộ danh sách Virtual Accounts!');
        break;
      }

      currentPage++;
    }

  } catch (err) {
    console.error('\n⚠️ [CẢNH BÁO QUÁ TRÌNH CÀO VA]:', err.message);
  } finally {
    // Xuất kết quả
    console.log('\n[Xuất dữ liệu] Đang lưu dữ liệu Virtual Accounts...');
    if (allAccounts.length > 0) {
      const jsonPath = exportVaToJson(allAccounts, config.outputDir, 'virtual_accounts_full.json');
      const csvPath = exportVaToCsv(allAccounts, config.outputDir, 'virtual_accounts.csv');
      generateVaSummaryReport(allAccounts, config.outputDir);

      console.log('\n========================================================================');
      console.log('                 HOÀN TẤT THU THẬP VIRTUAL ACCOUNTS');
      console.log(`  Tổng số tài khoản đã cào : ${allAccounts.length}`);
      console.log(`  File JSON chi tiết       : ${jsonPath}`);
      console.log(`  File CSV tổng hợp        : ${csvPath}`);
      console.log('========================================================================\n');
    } else {
      console.log('❌ Không có tài khoản nào được lưu.');
    }

    console.log('[Cleanup] Đang đóng trình duyệt...');
    await browser.close().catch(() => {});
  }
}

main();
