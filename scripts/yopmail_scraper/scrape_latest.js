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
const delayMs = parseInt(getArg('--delay', '700'), 10);

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

async function runLatestScraper() {
  console.log('========================================================================');
  console.log(`        YOPMAIL LATEST-ONLY SCRAPER`);
  console.log(`  Hòm thư mục tiêu : ${targetUser}@yopmail.com`);
  console.log(`  Chế độ           : Chỉ lấy email mới nhất`);
  console.log('========================================================================\n');

  if (!fs.existsSync(htmlDir)) {
    fs.mkdirSync(htmlDir, { recursive: true });
  }

  // Bước 1: Quét danh sách email — chỉ lấy 1 trang, 1 email mới nhất
  console.log('[1/4] Đang quét email mới nhất từ hòm thư...');
  const inboxData = await easyYopmail.getInbox(targetUser, {}, {
    LIMIT_PAGE: 1,
    LIMIT_MAIL: 1,
    ORDER: 'desc'
  });

  const emailList = inboxData.inbox || [];
  if (emailList.length === 0) {
    console.log('Hòm thư trống — không có email nào.');
    return;
  }

  const latestEmail = emailList[0];
  console.log(`✓ Email mới nhất: ID=${latestEmail.id} | Từ: ${latestEmail.from} | Tiêu đề: ${latestEmail.subject}\n`);

  // Bước 2: Khởi chạy trình duyệt
  console.log('[2/4] Đang khởi chạy trình duyệt Chromium...');
  const browser = await puppeteer.launch({
    headless: false,
    defaultViewport: null,
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

    console.log('[3/4] Mở YOPmail và đăng nhập...');
    await page.goto('https://yopmail.com/en/', { waitUntil: 'networkidle2' });

    await page.waitForSelector('input#login', { timeout: 15000 });
    await page.type('input#login', targetUser, { delay: 60 });
    await page.keyboard.press('Enter');

    console.log('Đang chờ giao diện load...');
    await sleep(4000);

    // Tự động click reCAPTCHA nếu có
    const recaptchaFrame = page.frames().find(f => f.url().includes('recaptcha/api2/anchor'));
    if (recaptchaFrame) {
      console.log('Nhấn ô CAPTCHA...');
      await recaptchaFrame.click('#recaptcha-anchor').catch(() => {});
    }

    // Chờ mở khóa
    let mailFrame = page.frames().find(f => f.name() === 'ifmail');
    let isUnlocked = false;
    console.log('Kiểm tra trạng thái bảo mật...');

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
          console.log('✅ XÁC MINH THÀNH CÔNG!\n');
          break;
        }
      }

      if ((Date.now() - startWait) % 10000 < 1500) {
        console.log('👉 Nếu thấy CAPTCHA ảnh, vui lòng giải trên màn hình...');
      }
      await sleep(1500);
    }

    if (!isUnlocked) {
      console.log('⚠️ Chưa mở khóa CAPTCHA — vẫn thử cào...');
    }

    // Bước 4: Cào nội dung email mới nhất
    console.log('[4/4] Đang cào nội dung email mới nhất...');
    const startTime = Date.now();

    // Điều hướng tới email cụ thể
    await page.evaluate((login, id) => {
      if (window.mailnav) {
        window.mailnav(`mail?b=${login}&id=m${id}`);
      } else {
        const f = window.frames['ifmail'];
        if (f) f.location.replace(`mail?b=${login}&id=m${id}`);
      }
    }, targetUser, latestEmail.id);

    await sleep(delayMs);

    // Trích xuất nội dung
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
      subject: latestEmail.subject,
      from: latestEmail.from,
      date: latestEmail.timestamp,
      bodyText: '',
      bodyHtml: '',
      error: err.message
    }));

    const safeSubject = mailData.subject || latestEmail.subject || '(No Subject)';
    const safeFrom = mailData.from || latestEmail.from || 'Unknown';
    const finalBodyText = mailData.bodyText || '';
    const finalBodyHtml = mailData.bodyHtml || '';

    // Lưu file HTML
    const safeFileName = `mail_001_${latestEmail.id.replace(/[^a-zA-Z0-9_-]/g, '')}.html`;
    const htmlFilePath = path.join(htmlDir, safeFileName);
    fs.writeFileSync(htmlFilePath, finalBodyHtml, 'utf-8');

    // Bóc tách links và OTP
    const links = extractLinks(finalBodyHtml);
    const otpCodes = extractOtp(finalBodyText);

    const record = {
      index: 1,
      id: latestEmail.id,
      inbox: `${targetUser}@yopmail.com`,
      from: safeFrom,
      subject: safeSubject,
      date: mailData.date || latestEmail.day || latestEmail.timestamp,
      timestamp: latestEmail.timestamp || '',
      page: latestEmail.page || 1,
      body_text: finalBodyText,
      body_html_file: `html/${safeFileName}`,
      extracted_links: links,
      extracted_codes: otpCodes,
      scraped_at: new Date().toISOString()
    };

    // Xuất kết quả
    console.log('\n========================================================================');
    console.log('   XUẤT DỮ LIỆU EMAIL MỚI NHẤT');
    console.log('========================================================================');

    // 1. JSON
    const jsonPath = path.join(outputDir, 'latest_email.json');
    fs.writeFileSync(jsonPath, JSON.stringify(record, null, 2), 'utf-8');
    console.log(`✓ [JSON] ${jsonPath}`);

    // 2. CSV
    const csvPath = path.join(outputDir, 'latest_email.csv');
    const escapeCsv = (str) => `"${String(str || '').replace(/"/g, '""').replace(/\r?\n/g, ' ')}"`;
    const csvLine = [
      1,
      escapeCsv(record.id),
      escapeCsv(record.inbox),
      escapeCsv(record.from),
      escapeCsv(record.subject),
      escapeCsv(record.date),
      record.page,
      escapeCsv(record.body_text),
      escapeCsv(record.body_html_file),
      escapeCsv(record.extracted_links.join('; ')),
      escapeCsv(record.extracted_codes.join('; ')),
      escapeCsv(record.scraped_at)
    ].join(',');
    fs.writeFileSync(csvPath, `Index,ID,Inbox,From,Subject,Date,Page,Body Text,HTML File,Extracted Links,Extracted Codes,Scraped At\n${csvLine}\n`, 'utf-8');
    console.log(`✓ [CSV]  ${csvPath}`);

    // 3. In ra console
    console.log(`\n📧 Email mới nhất:`);
    console.log(`   Từ:     ${record.from}`);
    console.log(`   Tiêu đề: ${record.subject}`);
    console.log(`   Ngày:   ${record.date}`);
    console.log(`   Nội dung: ${record.body_text.substring(0, 200)}${record.body_text.length > 200 ? '...' : ''}`);
    if (record.extracted_codes.length > 0) {
      console.log(`   🔐 Mã OTP: ${record.extracted_codes.join(', ')}`);
    }
    if (record.extracted_links.length > 0) {
      console.log(`   🔗 Links: ${record.extracted_links.length} link(s) tìm thấy`);
    }

    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    console.log(`\n🎉 HOÀN TẤT! (${elapsed}s)`);

  } catch (err) {
    console.error('Lỗi scraper:', err);
  } finally {
    await browser.close();
  }
}

runLatestScraper();