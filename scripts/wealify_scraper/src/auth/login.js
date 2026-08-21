const readline = require('readline');
const { saveSession, restoreSession, clearSession } = require('./session');
const config = require('../config');

function askConsole(query) {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });
  return new Promise(resolve => rl.question(query, ans => {
    rl.close();
    resolve(ans.trim());
  }));
}

async function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function typeHuman(page, selector, text) {
  await page.waitForSelector(selector, { timeout: 15000 });
  await page.click(selector);
  // Xoá text cũ nếu có
  await page.keyboard.down('Meta');
  await page.keyboard.press('KeyA');
  await page.keyboard.up('Meta');
  await page.keyboard.press('Backspace');

  for (const char of text) {
    await page.keyboard.type(char, { delay: Math.floor(Math.random() * 50) + 30 });
  }
}

async function isAlreadyLoggedIn(page) {
  try {
    // Kiểm tra xem có avatar, menu sidebar hoặc không còn ở trang login
    const currentUrl = page.url();
    if (currentUrl.includes('/login') || currentUrl.includes('/signin')) {
      return false;
    }

    const hasDashboardElement = await page.evaluate(() => {
      const text = document.body.innerText || '';
      return text.includes('Tổng quan') || 
             text.includes('Thẻ ảo') || 
             text.includes('Giao dịch') || 
             !!document.querySelector('.ant-avatar, [aria-label="User"], .user-profile, nav');
    });
    return hasDashboardElement;
  } catch (err) {
    return false;
  }
}

async function performLogin(page) {
  console.log('[Auth] Bắt đầu quy trình xác thực Wealify...');

  // Thử khôi phục session cũ
  const hasRestored = await restoreSession(page);
  
  console.log(`[Auth] Đang mở URL: ${config.baseUrl} ...`);
  await page.goto(config.baseUrl, { waitUntil: 'networkidle2', timeout: 45000 });

  if (hasRestored && await isAlreadyLoggedIn(page)) {
    console.log('✓ [Auth] Phiên đăng nhập trước đó vẫn còn hiệu lực! Bỏ qua bước điền mật khẩu.\n');
    return true;
  }

  console.log('[Auth] Cần đăng nhập tài khoản mới...');
  
  let username = config.username;
  let password = config.password;

  if (!username) {
    username = await askConsole('Nhập Email/Username Wealify: ');
  }
  if (!password) {
    password = await askConsole('Nhập Mật khẩu Wealify: ');
  }

  // Tìm ô nhập Email/Username
  const emailSelectors = [
    'input[type="email"]',
    'input[name="email"]',
    'input[name="username"]',
    'input[placeholder*="email" i]',
    'input[placeholder*="tài khoản" i]',
    'input#email',
    'input#username'
  ];

  let emailInputFound = false;
  for (const sel of emailSelectors) {
    if (await page.$(sel)) {
      console.log(`[Auth] Đang điền tài khoản vào: ${sel}`);
      await typeHuman(page, sel, username);
      emailInputFound = true;
      break;
    }
  }

  if (!emailInputFound) {
    // Thử fallback selector input text đầu tiên
    const firstInput = await page.$('input:not([type="hidden"])');
    if (firstInput) {
      await firstInput.click();
      await firstInput.type(username, { delay: 40 });
    } else {
      throw new Error('Không tìm thấy ô nhập tài khoản/email trên trang web.');
    }
  }

  await delay(500);

  // Tìm ô nhập Password
  const passwordSelectors = [
    'input[type="password"]',
    'input[name="password"]',
    'input[placeholder*="mật khẩu" i]',
    'input[placeholder*="password" i]',
    'input#password'
  ];

  let passwordInputFound = false;
  for (const sel of passwordSelectors) {
    if (await page.$(sel)) {
      console.log(`[Auth] Đang điền mật khẩu vào: ${sel}`);
      await typeHuman(page, sel, password);
      passwordInputFound = true;
      break;
    }
  }

  if (!passwordInputFound) {
    throw new Error('Không tìm thấy ô nhập mật khẩu.');
  }

  await delay(500);

  // Nhấn nút Submit / Đăng nhập
  console.log('[Auth] Đang gửi yêu cầu đăng nhập...');
  const submitButtonSelectors = [
    'button[type="submit"]',
    'button:has-text("Đăng nhập")',
    'button:has-text("Sign in")',
    'button:has-text("Login")',
    'button.ant-btn-primary'
  ];

  let submitted = false;
  for (const sel of submitButtonSelectors) {
    const btn = await page.$(sel);
    if (btn) {
      await btn.click();
      submitted = true;
      break;
    }
  }

  if (!submitted) {
    await page.keyboard.press('Enter');
  }

  // Chờ điều hướng hoặc xuất hiện màn hình 2FA
  console.log('[Auth] Đang chờ kết quả phản hồi...');
  await delay(3000);

  // Kiểm tra nếu có OTP / 2FA
  const isOtpScreen = await page.evaluate(() => {
    const text = document.body.innerText || '';
    return text.includes('Mã xác thực') || 
           text.includes('OTP') || 
           text.includes('Verification code') || 
           text.includes('Two-factor') ||
           !!document.querySelector('input[placeholder*="OTP"], input[name*="otp"], input[autocomplete="one-time-code"]');
  });

  if (isOtpScreen) {
    console.log('\n⚠️ [Auth] Phát hiện yêu cầu xác thực 2FA/OTP!');
    let otpCode = '';
    
    if (config.otpAuto && config.otpYopmailUser) {
      console.log(`[Auth] Đang thử lấy OTP tự động từ Yopmail (${config.otpYopmailUser})...`);
      // Optional hook for easy-yopmail if available
      try {
        const easyYopmail = require('easy-yopmail');
        const inbox = await easyYopmail.getInbox(config.otpYopmailUser);
        if (inbox && inbox.inbox && inbox.inbox.length > 0) {
          const latestMail = inbox.inbox[0];
          console.log(`[Auth] Đọc mail mới nhất: ${latestMail.subject}`);
          const match = latestMail.subject.match(/\b\d{4,8}\b/);
          if (match) otpCode = match[0];
        }
      } catch (err) {
        console.log('[Auth] Không thể đọc Yopmail tự động:', err.message);
      }
    }

    if (!otpCode) {
      otpCode = await askConsole('👉 Vui lòng nhập mã OTP gửi về thiết bị/email của bạn: ');
    }

    const otpInput = await page.$('input[placeholder*="OTP"], input[name*="otp"], input[autocomplete="one-time-code"], input[type="text"], input[type="number"]');
    if (otpInput) {
      await otpInput.click();
      await otpInput.type(otpCode, { delay: 50 });
      await delay(500);
      await page.keyboard.press('Enter');
    }
  }

  // Đợi đăng nhập hoàn tất
  await page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 30000 }).catch(() => {});
  await delay(2000);

  if (await isAlreadyLoggedIn(page)) {
    console.log('✓ [Auth] Đăng nhập Wealify thành công!');
    await saveSession(page);
    return true;
  } else {
    throw new Error('Đăng nhập không thành công hoặc phiên chưa sẵn sàng. Vui lòng kiểm tra lại tài khoản/mật khẩu.');
  }
}

module.exports = {
  performLogin,
  isAlreadyLoggedIn
};
