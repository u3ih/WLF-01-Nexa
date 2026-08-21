const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const easyYopmail = require('easy-yopmail');
puppeteer.use(StealthPlugin());

// Đọc tham số dòng lệnh
const args = process.argv.slice(2);
function getArg(flag, defaultValue) {
  const idx = args.indexOf(flag);
  if (idx !== -1 && args[idx + 1]) return args[idx + 1];
  return defaultValue;
}

const targetUser = getArg('--user', 'wealifytester');
const outputDir = path.resolve(getArg('--output', path.join(__dirname, 'output', targetUser)));
const htmlDir = path.join(outputDir, 'html');
const maxEmails = parseInt(getArg('--limit', '0'), 10); // 0 = all
const delayMs = parseInt(getArg('--delay', '700'), 10);
const headless = getArg('--headless', 'false').toLowerCase() === 'true';
const requireUnlocked = getArg('--require-unlocked', 'false').toLowerCase() === 'true';

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function extractLinks(html) {
  const links = [];
  const regex = /href=[\"'](https?:\/\/[^\"']+)[\"']/gi;
  let match;
  while ((match = regex.exec(html)) !== null) {
    if (!links.includes(match[1])) {
      links.push(match[1]);
    }
  }
  return links;
}

function extractOtp(text) {
  const codes = [];
  const regex = /\b\d{4,8}\b/g;
  let match;
  while ((match = regex.exec(text)) !== null) {
    if (!codes.includes(match[0])) {
      codes.push(match[0]);
    }
  }
  return codes;
}

async function runFullScraper() {
  console.log('========================================================================');
  console.log(`        YOPMAIL FULL CONTENT & OTP SCRAPER`);
  console.log(`  Hòm thư mục tiêu : ${targetUser}@yopmail.com`);
  console.log(`  Thư mục lưu trữ  : ${outputDir}`);
  console.log('========================================================================\n');

  if (!fs.existsSync(htmlDir)) {
    fs.mkdirSync(htmlDir, { recursive: true });
  }

  // Bước 1: Quét danh sách email từ easy-yopmail API
  console.log('[1/4] Đang quét danh sách toàn bộ ID email trong hòm thư...');
  const inboxData = await easyYopmail.getInbox(targetUser, {}, {
    LIMIT_PAGE: 50,
    LIMIT_MAIL: 0,
    ORDER: 'desc'
  });

  const emailList = inboxData.inbox || [];
  const totalEmails = maxEmails > 0 ? Math.min(maxEmails, emailList.length) : emailList.length;
  console.log(`✓ Đã tìm thấy: ${emailList.length} emails trên ${inboxData.exploredPageCount || 1} trang.`);
  console.log(`✓ Sẽ cào toàn bộ nội dung cho: ${totalEmails} emails.\n`);

  if (totalEmails === 0) {
    console.log('Hòm thư trống.');
    fs.writeFileSync(path.join(outputDir, 'emails_full.json'), '[]\n', 'utf-8');
    return;
  }

  // Bước 2: Khởi chạy trình duyệt
  console.log('[2/4] Đang khởi chạy trình duyệt Chromium...');
  let browser;
  browser = await puppeteer.launch({
    headless,
    defaultViewport: headless ? { width: 1400, height: 900 } : null,
    args: [
      '--start-maximized',
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage'
    ]
  });

  try {
    const page = await browser.newPage();
    await page.setUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
    await page.setViewport({ width: 1400, height: 900 });

    console.log(`[3/4] Mở trang YOPmail và đăng nhập: ${targetUser} ...`);
    await page.goto('https://yopmail.com/en/', { waitUntil: 'networkidle2' });

    await page.waitForSelector('input#login', { timeout: 15000 });
    await page.type('input#login', targetUser, { delay: 60 });
    await page.keyboard.press('Enter');

    console.log('Đang chờ tải giao diện và frame email...');
    await sleep(4000);

    // Tự động click vào checkbox reCAPTCHA nếu có
    const recaptchaFrame = page.frames().find(f => f.url().includes('recaptcha/api2/anchor'));
    if (recaptchaFrame) {
      console.log('Tự động nhấn vào ô xác minh CAPTCHA...');
      await recaptchaFrame.click('#recaptcha-anchor').catch(() => {});
    }

    // Chờ frame ifmail sẵn sàng
    let mailFrame = page.frames().find(f => f.name() === 'ifmail');
    
    // Kiểm tra xem có đang bị CAPTCHA chặn không
    let isUnlocked = false;
    console.log('Kiểm tra trạng thái xác minh bảo mật...');

    const startWait = Date.now();
    while (Date.now() - startWait < 90000) {
      mailFrame = page.frames().find(f => f.name() === 'ifmail');
      if (mailFrame) {
        const check = await mailFrame.evaluate(() => {
          const mailEl = document.querySelector('#mail');
          const text = document.body ? document.body.innerText : '';
          return mailEl !== null && !text.includes('Complete the CAPTCHA');
        }).catch(() => false);

        if (check) {
          isUnlocked = true;
          console.log('✅ XÁC MINH THÀNH CÔNG! Nội dung email đã được mở khóa.\n');
          break;
        }
      }

      // Thông báo cho người dùng nếu cần giải ảnh
      if ((Date.now() - startWait) % 10000 < 1500) {
        console.log('👉 [HƯỚNG DẪN]: Nếu trình duyệt đang hiển thị bảng hình ảnh CAPTCHA, vui lòng giải trên màn hình...');
      }

      await sleep(1500);
    }

    if (!isUnlocked) {
      console.log('⚠️ Chưa mở khóa được CAPTCHA. Tool vẫn sẽ tiếp tục thử cào...');
      if (requireUnlocked) {
        throw new Error('YOPmail CAPTCHA is still locked; refusing to import incomplete content');
      }
    }

    // Bước 4: Lặp qua từng email và cào nội dung
    console.log(`[4/4] Bắt đầu cào toàn bộ ${totalEmails} emails (HTML + Text + Links + OTP)...`);
    const allEmails = [];
    const startTime = Date.now();

    for (let i = 0; i < totalEmails; i++) {
      const item = emailList[i];
      const mailId = item.id;
      const progress = `[${i + 1}/${totalEmails}]`;

      // Điều hướng frame ifmail tới email cụ thể
      await page.evaluate((login, id) => {
        if (window.mailnav) {
          window.mailnav(`mail?b=${login}&id=m${id}`);
        } else {
          const f = window.frames['ifmail'];
          if (f) f.location.replace(`mail?b=${login}&id=m${id}`);
        }
      }, targetUser, mailId);

      await sleep(delayMs);

      // Trích xuất nội dung từ ifmail
      mailFrame = page.frames().find(f => f.name() === 'ifmail') || mailFrame;
      const mailData = await mailFrame.evaluate(() => {
        const subjEl = document.querySelector('div.ellipsis.nw.b') || document.querySelector('title');
        const fromEl = document.querySelector('.ellipsis.b') || document.querySelector('#mailmail') || document.querySelector('div.fl > div.md.text.zoom.nw.f18 > span.ellipsis:last-child');
        const dateEl = document.querySelector('div.fl > div.md.text.zoom.nw.f24 > span.ellipsis:last-child') || document.querySelector('.ycptdate');
        const mailEl = document.querySelector('#mail');

        return {
          subject: subjEl ? subjEl.innerText.trim() : '',
          from: fromEl ? fromEl.innerText.trim() : '',
          date: dateEl ? dateEl.innerText.trim() : '',
          bodyText: mailEl ? mailEl.innerText.trim() : (document.body ? document.body.innerText.trim() : ''),
          bodyHtml: mailEl ? mailEl.innerHTML : (document.body ? document.body.innerHTML : '')
        };
      }).catch(err => ({
        subject: item.subject,
        from: item.from,
        date: item.timestamp,
        bodyText: '',
        bodyHtml: '',
        error: err.message
      }));

      const safeSubject = mailData.subject || item.subject || '(No Subject)';
      const safeFrom = mailData.from || item.from || 'Unknown';
      const finalBodyText = mailData.bodyText || '';
      const finalBodyHtml = mailData.bodyHtml || '';

      // Lưu file HTML
      const safeFileName = `mail_${String(i + 1).padStart(3, '0')}_${mailId.replace(/[^a-zA-Z0-9_-]/g, '')}.html`;
      const htmlFilePath = path.join(htmlDir, safeFileName);
      fs.writeFileSync(htmlFilePath, finalBodyHtml, 'utf-8');

      // Bóc tách links và mã OTP
      const links = extractLinks(finalBodyHtml);
      const otpCodes = extractOtp(finalBodyText);

      const record = {
        index: i + 1,
        id: mailId,
        inbox: `${targetUser}@yopmail.com`,
        from: safeFrom,
        subject: safeSubject,
        date: mailData.date || item.day || item.timestamp,
        timestamp: item.timestamp || '',
        page: item.page || 1,
        body_text: finalBodyText,
        body_html_file: `html/${safeFileName}`,
        extracted_links: links,
        extracted_codes: otpCodes,
        scraped_at: new Date().toISOString()
      };

      allEmails.push(record);
      const otpStr = otpCodes.length > 0 ? ` | OTP: [${otpCodes.join(', ')}]` : '';
      console.log(`${progress} ✓ Đã cào: "${safeSubject.substring(0, 42)}" | Text: ${finalBodyText.length} ký tự${otpStr}`);
    }

    // Xuất kết quả
    console.log('\n========================================================================');
    console.log('   ĐANG XUẤT TẤT CẢ DỮ LIỆU ĐẦU RA');
    console.log('========================================================================');

    // 1. JSON
    const jsonPath = path.join(outputDir, 'emails_full.json');
    fs.writeFileSync(jsonPath, JSON.stringify(allEmails, null, 2), 'utf-8');
    console.log(`✓ [JSON] Đã lưu đầy đủ: ${jsonPath}`);

    // 2. CSV
    const csvPath = path.join(outputDir, 'emails_full.csv');
    const csvHeaders = ['Index', 'ID', 'Inbox', 'From', 'Subject', 'Date', 'Page', 'Body Text', 'HTML File', 'Extracted Links', 'Extracted Codes', 'Scraped At'];
    const escapeCsv = (str) => `"${String(str || '').replace(/"/g, '""').replace(/\r?\n/g, ' ')}"`;
    
    const csvRows = [
      csvHeaders.join(','),
      ...allEmails.map(e => [
        e.index,
        escapeCsv(e.id),
        escapeCsv(e.inbox),
        escapeCsv(e.from),
        escapeCsv(e.subject),
        escapeCsv(e.date),
        e.page,
        escapeCsv(e.body_text),
        escapeCsv(e.body_html_file),
        escapeCsv(e.extracted_links.join('; ')),
        escapeCsv(e.extracted_codes.join('; ')),
        escapeCsv(e.scraped_at)
      ].join(','))
    ];
    fs.writeFileSync(csvPath, csvRows.join('\n'), 'utf-8');
    console.log(`✓ [CSV]  Đã lưu bảng tính: ${csvPath}`);

    // 3. Markdown Report
    const reportPath = path.join(outputDir, 'full_report.md');
    let md = `# Báo Cáo Chi Tiết Scrape Nội Dung Email YOPmail\n\n`;
    md += `- **Hòm thư**: \`${targetUser}@yopmail.com\`\n`;
    md += `- **Tổng số email đã lấy Content**: **${allEmails.length}** emails\n`;
    md += `- **Thời gian hoàn tất**: ${new Date().toLocaleString()}\n`;
    md += `- **Tổng thời gian chạy**: ${((Date.now() - startTime) / 1000).toFixed(1)} giây\n\n`;

    md += `## Danh Sách Chi Tiết Từng Email\n\n`;
    allEmails.forEach(e => {
      md += `### ${e.index}. ${e.subject}\n`;
      md += `- **Người gửi**: ${e.from}\n`;
      md += `- **Thời gian**: ${e.date}\n`;
      md += `- **File HTML gốc**: [\`${e.body_html_file}\`](${e.body_html_file})\n`;
      if (e.extracted_codes.length > 0) {
        md += `- **Mã OTP / Mã xác nhận**: \`${e.extracted_codes.join('`, `')}\`\n`;
      }
      if (e.extracted_links.length > 0) {
        md += `- **Liên kết trong email**: ${e.extracted_links.map(l => `<${l}>`).join(', ')}\n`;
      }
      md += `\n**Nội dung chi tiết (Text Content)**:\n\`\`\`text\n${e.body_text || '(Trống)'}\n\`\`\`\n\n---\n\n`;
    });

    fs.writeFileSync(reportPath, md, 'utf-8');
    console.log(`✓ [Markdown] Đã lưu báo cáo: ${reportPath}`);

    console.log(`\n🎉 HOÀN TẤT XUẤT TOÀN BỘ ${allEmails.length} EMAIL KÈM NỘI DUNG VÀ FILE HTML!`);

  } catch (err) {
    console.error('Lỗi scraper:', err);
    process.exitCode = 1;
  } finally {
    if (browser) {
      await browser.close();
    }
  }
}

runFullScraper();
