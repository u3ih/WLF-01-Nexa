const fs = require('fs');
const path = require('path');
const easyYopmail = require('easy-yopmail');

// Cấu hình tham số dòng lệnh hoặc mặc định
const args = process.argv.slice(2);
function getArg(flag, defaultValue) {
  const idx = args.indexOf(flag);
  if (idx !== -1 && args[idx + 1]) return args[idx + 1];
  return defaultValue;
}

const targetUser = getArg('--user', 'wealifytester');
const outputDir = path.resolve(getArg('--output', path.join(__dirname, 'output', targetUser)));
const maxPages = parseInt(getArg('--pages', '20'), 10);

async function main() {
  console.log('====================================================');
  console.log(`  YOPMAIL SCRAPER (Powered by easy-yopmail)`);
  console.log(`  Target Inbox : ${targetUser}@yopmail.com`);
  console.log(`  Output Dir   : ${outputDir}`);
  console.log(`  Max Pages    : ${maxPages}`);
  console.log('====================================================\n');

  // Đảm bảo thư mục output tồn tại
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  console.log(`[1/3] Đang kết nối YOPmail và lấy toàn bộ danh sách thư...`);
  const startTime = Date.now();

  try {
    const inboxData = await easyYopmail.getInbox(targetUser, {}, {
      LIMIT_PAGE: maxPages,
      LIMIT_MAIL: 0,
      ORDER: 'desc'
    });

    const emails = inboxData.inbox || [];
    const totalFound = emails.length;
    console.log(`✓ Đã tìm thấy: ${totalFound} emails trên ${inboxData.exploredPageCount || 1} trang.\n`);

    if (totalFound === 0) {
      console.log('Hòm thư trống hoặc không có email nào.');
      return;
    }

    // Chuẩn hóa dữ liệu
    console.log(`[2/3] Đang xử lý và chuẩn hóa dữ liệu email...`);
    const formattedEmails = emails.map((item, index) => {
      return {
        index: index + 1,
        id: item.id,
        inbox: `${targetUser}@yopmail.com`,
        from: item.from || 'Unknown',
        subject: item.subject || '(No Subject)',
        day: item.day || '',
        timestamp: item.timestamp || '',
        page: item.page || 1,
        scraped_at: new Date().toISOString()
      };
    });

    // 1. Lưu file JSON
    const jsonPath = path.join(outputDir, 'emails.json');
    fs.writeFileSync(jsonPath, JSON.stringify(formattedEmails, null, 2), 'utf-8');
    console.log(`✓ Đã xuất file JSON: ${jsonPath}`);

    // 2. Lưu file CSV
    const csvPath = path.join(outputDir, 'emails.csv');
    const csvHeaders = ['Index', 'ID', 'Inbox', 'From', 'Subject', 'Day', 'Timestamp', 'Page', 'Scraped At'];
    const escapeCsv = (str) => `"${String(str || '').replace(/"/g, '""')}"`;
    
    const csvRows = [
      csvHeaders.join(','),
      ...formattedEmails.map(e => [
        e.index,
        escapeCsv(e.id),
        escapeCsv(e.inbox),
        escapeCsv(e.from),
        escapeCsv(e.subject),
        escapeCsv(e.day),
        escapeCsv(e.timestamp),
        e.page,
        escapeCsv(e.scraped_at)
      ].join(','))
    ];
    fs.writeFileSync(csvPath, csvRows.join('\n'), 'utf-8');
    console.log(`✓ Đã xuất file CSV: ${csvPath}`);

    // 3. Tạo file Báo cáo tổng kết Markdown
    const reportPath = path.join(outputDir, 'summary_report.md');
    const senderCounts = {};
    formattedEmails.forEach(e => {
      senderCounts[e.from] = (senderCounts[e.from] || 0) + 1;
    });

    let reportMd = `# Báo Cáo Scrape Email YOPmail: \`${targetUser}@yopmail.com\`\n\n`;
    reportMd += `- **Thời gian thực hiện**: ${new Date().toLocaleString()}\n`;
    reportMd += `- **Tổng số email cào được**: **${totalFound}** emails\n`;
    reportMd += `- **Số trang đã quét**: ${inboxData.exploredPageCount || 1} trang\n`;
    reportMd += `- **Thời gian chạy**: ${((Date.now() - startTime) / 1000).toFixed(2)} giây\n\n`;

    reportMd += `## Thống kê người gửi (Senders)\n\n`;
    reportMd += `| Người gửi (From) | Số lượng thư |\n`;
    reportMd += `| :--- | :--- |\n`;
    Object.entries(senderCounts).forEach(([sender, count]) => {
      reportMd += `| ${sender} | **${count}** |\n`;
    });

    reportMd += `\n## Danh sách 20 email mới nhất\n\n`;
    reportMd += `| # | Người gửi | Tiêu đề | Thời gian | Ngày |\n`;
    reportMd += `| :-: | :--- | :--- | :--- | :--- |\n`;
    formattedEmails.slice(0, 20).forEach(e => {
      reportMd += `| ${e.index} | ${e.from} | ${e.subject} | ${e.timestamp} | ${e.day} |\n`;
    });

    if (formattedEmails.length > 20) {
      reportMd += `\n*...và còn ${formattedEmails.length - 20} email khác trong các file \`emails.json\` và \`emails.csv\`.*\n`;
    }

    fs.writeFileSync(reportPath, reportMd, 'utf-8');
    console.log(`✓ Đã xuất báo cáo tổng quan: ${reportPath}`);

    console.log(`\n[3/3] Hoàn tất quá trình scrape thành công trong ${((Date.now() - startTime) / 1000).toFixed(2)}s!`);
  } catch (err) {
    console.error('Lỗi trong quá trình scrape:', err);
    process.exit(1);
  }
}

main();
