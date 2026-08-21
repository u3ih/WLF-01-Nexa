const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
puppeteer.use(StealthPlugin());

const path = require('path');
const fs = require('fs');
const config = require('./src/config');
const { performLogin } = require('./src/auth/login');
const NetworkInterceptor = require('./src/scraper/interceptor');
const {
  navigateToCardsPage,
  scrapeCardTableRows,
  scrapeCardDrawerDetail,
  closeCardDrawer
} = require('./src/scraper/cards_scraper');
const { goToNextPage } = require('./src/scraper/pagination');
const { normalizeCardRecord } = require('./src/parser/cards_normalizer');
const {
  exportCardsToJson,
  exportCardsToCsv,
  generateCardsSummaryReport
} = require('./src/storage/cards_exporter');

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function main() {
  console.log('========================================================================');
  console.log('         WEALIFY VIRTUAL CARDS & CARD DETAILS CRAWLER');
  console.log('========================================================================');
  console.log(`  Mục tiêu URL        : ${config.baseUrl}/vc/list`);
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

  const allCards = [];
  const processedCardKeys = new Set();

  try {
    const page = await browser.newPage();
    await page.setUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36');
    await page.setViewport({ width: 1440, height: 900 });

    const interceptor = new NetworkInterceptor();
    interceptor.setup(page);

    // [2/4] Đăng nhập & Xác thực
    console.log('\n[2/4] Tiến hành đăng nhập và xác thực...');
    await performLogin(page);

    // [3/4] Điều hướng tới Danh sách thẻ
    console.log('\n[3/4] Điều hướng tới mục Danh sách Thẻ ảo (/vc/list)...');
    await navigateToCardsPage(page);
    await delay(3000);

    // [4/4] Cào dữ liệu thẻ và chi tiết Drawer
    console.log('\n[4/4] Bắt đầu cào dữ liệu danh sách thẻ và chi tiết Drawer...');
    let currentPage = 1;

    while (true) {
      console.log(`\n💳 Đang xử lý Trang thẻ #${currentPage}...`);
      await delay(1000);

      const cardRows = await scrapeCardTableRows(page);
      console.log(`  ✓ Tìm thấy ${cardRows.length} thẻ trên giao diện.`);

      if (cardRows.length === 0) {
        console.log('[Info] Không có thẻ nào trên trang này.');
        break;
      }

      for (let i = 0; i < cardRows.length; i++) {
        const rawRow = cardRows[i];
        const cardKey = rawRow.last4 || rawRow.cardName || `CARD_${i}`;

        if (processedCardKeys.has(cardKey)) {
          continue;
        }

        let cardDetail = null;
        if (config.fullDrawer) {
          process.stdout.write(`  [${i + 1}/${cardRows.length}] Mở chi tiết thẻ: ${rawRow.cardName} (**** ${rawRow.last4}) ... `);
          cardDetail = await scrapeCardDrawerDetail(page, i, rawRow.cardName, rawRow.last4);
          console.log(cardDetail ? '✓ (Thành công)' : '⚠️ (Lấy dữ liệu bảng)');
        }

        const normalized = normalizeCardRecord(rawRow, cardDetail);
        allCards.push(normalized);
        processedCardKeys.add(cardKey);
      }

      await closeCardDrawer(page);

      if (config.pageLimit > 0 && currentPage >= config.pageLimit) {
        break;
      }

      const hasNext = await goToNextPage(page);
      if (!hasNext) {
        console.log('\n✓ Đã quét hết toàn bộ danh sách thẻ ảo!');
        break;
      }

      currentPage++;
    }

  } catch (err) {
    console.error('\n⚠️ [CẢNH BÁO QUÁ TRÌNH CÀO THẺ]:', err.message);
  } finally {
    // Xuất kết quả
    console.log('\n[Xuất dữ liệu] Đang lưu dữ liệu thẻ ảo...');
    if (allCards.length > 0) {
      const jsonPath = exportCardsToJson(allCards, config.outputDir, 'cards_full.json');
      const csvPath = exportCardsToCsv(allCards, config.outputDir, 'cards.csv');
      generateCardsSummaryReport(allCards, config.outputDir);

      console.log('\n========================================================================');
      console.log('                      HOÀN TẤT THU THẬP THẺ ẢO');
      console.log(`  Tổng số thẻ đã cào       : ${allCards.length}`);
      console.log(`  File JSON chi tiết       : ${jsonPath}`);
      console.log(`  File CSV tổng hợp        : ${csvPath}`);
      console.log('========================================================================\n');
    } else {
      console.log('❌ Không có thẻ nào được lưu.');
    }

    console.log('[Cleanup] Đang đóng trình duyệt...');
    await browser.close().catch(() => {});
  }
}

main();
