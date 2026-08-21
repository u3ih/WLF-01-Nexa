const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
puppeteer.use(StealthPlugin());

const path = require('path');
const fs = require('fs');
const config = require('./src/config');
const { performLogin } = require('./src/auth/login');
const NetworkInterceptor = require('./src/scraper/interceptor');
const {
  navigateToTransactionsPage,
  scrapeTableRows,
  scrapeRowSidebarDetail,
  closeSidebarDrawer
} = require('./src/scraper/drawer_scraper');
const { applyDateFilter, goToNextPage } = require('./src/scraper/pagination');
const { normalizeDomRow } = require('./src/parser/normalizer');
const { exportToJson } = require('./src/storage/json_exporter');
const { exportToCsv } = require('./src/storage/csv_exporter');

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function main() {
  console.log('========================================================================');
  console.log('         WEALIFY TRANSACTIONS & SIDEBAR DRAWER CRAWLER');
  console.log('========================================================================');
  console.log(`  Mục tiêu URL        : ${config.baseUrl}`);
  console.log(`  Tài khoản           : ${config.username || '(Nhập khi chạy)'}`);
  console.log(`  Chế độ Headless     : ${config.headless ? 'Bật (Ẩn cửa sổ)' : 'Tắt (Hiện trình duyệt)'}`);
  console.log(`  Cào chi tiết Sidebar: ${config.fullDrawer ? 'Bật' : 'Tắt'}`);
  console.log(`  Thư mục xuất file   : ${config.outputDir}`);
  if (config.dateFrom || config.dateTo) {
    console.log(`  Lọc thời gian       : ${config.dateFrom || '...'} -> ${config.dateTo || 'nay'}`);
  }
  console.log('========================================================================\n');

  console.log('[1/5] Khởi động trình duyệt Chromium Stealth...');
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

  const allNormalizedTransactions = [];
  const processedTxIds = new Set();

  try {
    const page = await browser.newPage();
    await page.setUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36');
    await page.setViewport({ width: 1440, height: 900 });

    // Khởi tạo bộ nghe mạng (Network Interceptor)
    const interceptor = new NetworkInterceptor();
    interceptor.setup(page);

    // [2/5] Đăng nhập & Quản lý Session
    console.log('\n[2/5] Tiến hành đăng nhập và xác thực...');
    await performLogin(page);

    // [3/5] Điều hướng tới trang Giao dịch
    console.log('\n[3/5] Điều hướng tới mục Giao dịch Thẻ ảo...');
    await navigateToTransactionsPage(page);
    await delay(3000);

    // Áp dụng bộ lọc ngày nếu có
    if (config.dateFrom || config.dateTo) {
      await applyDateFilter(page, config.dateFrom, config.dateTo);
      await delay(2000);
    }

    // [4/5] Thu thập dữ liệu bảng & Sidebar Drawer
    console.log('\n[4/5] Bắt đầu cào dữ liệu danh sách và chi tiết Sidebar...');
    let currentPage = 1;

    while (true) {
      console.log(`\n📄 Đang kiểm tra dữ liệu Trang ${currentPage}...`);
      await delay(1000);

      const tableRows = await scrapeTableRows(page);
      console.log(`  ✓ Tìm thấy ${tableRows.length} dòng trên giao diện.`);

      if (tableRows.length === 0) {
        console.log('[Info] Không có dòng giao dịch nào trên trang này.');
        break;
      }

      // Lọc các dòng chưa từng xử lý
      const newRowsToProcess = tableRows.filter(r => r.detectedTxId && !processedTxIds.has(r.detectedTxId));

      if (newRowsToProcess.length === 0 && currentPage > 1) {
        console.log('✓ [Pagination] Tất cả giao dịch trên trang này đã được cào trước đó. Dừng lại (tránh lặp vô hạn).');
        break;
      }

      console.log(`  🚀 Bắt đầu cào ${tableRows.length} giao dịch...`);
      for (let i = 0; i < tableRows.length; i++) {
        const rawRow = tableRows[i];
        const txId = rawRow.detectedTxId || `ROW_${currentPage}_${i + 1}`;

        if (processedTxIds.has(txId)) {
          continue; // Đã cào rồi, bỏ qua
        }

        let sidebarDetail = null;
        if (config.fullDrawer) {
          process.stdout.write(`  [${i + 1}/${tableRows.length}] Mở chi tiết: ${txId} ... `);
          sidebarDetail = await scrapeRowSidebarDetail(page, i, txId);
          console.log(sidebarDetail ? '✓' : '⚠️ (Lấy dữ liệu bảng)');
        }

        // Lấy dữ liệu API nếu có
        const apiDetail = interceptor.getCapturedDetail(txId);
        const mergedDetail = Object.assign({}, apiDetail || {}, sidebarDetail || {});

        const normalized = normalizeDomRow(rawRow, mergedDetail);
        allNormalizedTransactions.push(normalized);
        processedTxIds.add(txId);
      }

      // Đóng sidebar khi quét xong trang
      await closeSidebarDrawer(page);

      if (config.pageLimit > 0 && currentPage >= config.pageLimit) {
        console.log(`[Pagination] Đã đạt giới hạn số trang cấu hình (--limit ${config.pageLimit}). Dừng lại.`);
        break;
      }

      // Kiểm tra chuyển sang trang kế tiếp
      const hasNext = await goToNextPage(page);
      if (!hasNext) {
        console.log('\n✓ [Pagination] Đã quét hết toàn bộ các trang giao dịch!');
        break;
      }

      currentPage++;
    }

    // Kết hợp thêm các giao dịch chỉ xuất hiện trong Network API (nếu có)
    const apiTxList = interceptor.getCapturedList();
    if (apiTxList.length > 0) {
      console.log(`\n[Interceptor] Kiểm tra bổ sung ${apiTxList.length} giao dịch từ Network API...`);
      for (const apiItem of apiTxList) {
        const id = String(apiItem.id || apiItem.transaction_id || apiItem.code || '');
        if (id && !processedTxIds.has(id)) {
          allNormalizedTransactions.push(apiItem);
          processedTxIds.add(id);
        }
      }
    }

  } catch (err) {
    console.error('\n⚠️ [CẢNH BÁO QUÁ TRÌNH CÀO]:', err.message);
  } finally {
    // [5/5] Xuất kết quả ra file (luôn chạy kể cả khi có gián đoạn)
    console.log('\n[5/5] Đang lưu dữ liệu đã thu thập được...');
    if (allNormalizedTransactions.length > 0) {
      const jsonPath = exportToJson(allNormalizedTransactions, config.outputDir, 'transactions_full.json');
      const csvPath = exportToCsv(allNormalizedTransactions, config.outputDir, 'transactions.csv');
      generateSummaryReport(allNormalizedTransactions, config.outputDir);

      console.log('\n========================================================================');
      console.log('                      HOÀN TẤT THU THẬP DỮ LIỆU');
      console.log(`  Tổng số giao dịch đã cào : ${allNormalizedTransactions.length}`);
      console.log(`  File JSON chi tiết       : ${jsonPath}`);
      console.log(`  File CSV tổng hợp        : ${csvPath}`);
      console.log('========================================================================\n');
    } else {
      console.log('❌ Không có giao dịch nào được lưu.');
    }

    console.log('[Cleanup] Đang đóng trình duyệt...');
    await browser.close().catch(() => {});
  }
}

function generateSummaryReport(transactions, outputDir) {
  let totalInflow = 0;
  let totalOutflow = 0;
  const typeCounts = {};
  const statusCounts = {};

  for (const t of transactions) {
    const amt = t.amount || 0;
    if (amt > 0) totalInflow += amt;
    else totalOutflow += Math.abs(amt);

    typeCounts[t.type] = (typeCounts[t.type] || 0) + 1;
    statusCounts[t.status] = (statusCounts[t.status] || 0) + 1;
  }

  const report = [
    '# Báo cáo tổng hợp dữ liệu giao dịch Wealify',
    `*Thời gian tạo: ${new Date().toISOString()}*`,
    '',
    '## 1. Tổng quan số liệu',
    `- **Tổng số giao dịch đã cào:** ${transactions.length}`,
    `- **Tổng tiền vào (Inflow):** +$${totalInflow.toFixed(2)}`,
    `- **Tổng tiền ra (Outflow):** -$${totalOutflow.toFixed(2)}`,
    '',
    '## 2. Thống kê theo loại giao dịch',
    '| Loại giao dịch | Số lượng |',
    '|---|---|',
    ...Object.entries(typeCounts).map(([k, v]) => `| ${k} | ${v} |`),
    '',
    '## 3. Thống kê theo trạng thái',
    '| Trạng thái | Số lượng |',
    '|---|---|',
    ...Object.entries(statusCounts).map(([k, v]) => `| ${k} | ${v} |`),
    ''
  ].join('\n');

  fs.writeFileSync(path.join(outputDir, 'summary_report.md'), report, 'utf-8');
}

main();
