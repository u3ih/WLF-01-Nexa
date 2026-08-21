const fs = require('fs');
const path = require('path');
const config = require('../config');

const COOKIE_FILE = path.join(config.sessionDir, 'cookies.json');
const STORAGE_FILE = path.join(config.sessionDir, 'local_storage.json');

async function saveSession(page) {
  try {
    const cookies = await page.cookies();
    fs.writeFileSync(COOKIE_FILE, JSON.stringify(cookies, null, 2), 'utf-8');

    const localStorageData = await page.evaluate(() => {
      const json = {};
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        json[key] = localStorage.getItem(key);
      }
      return json;
    });
    fs.writeFileSync(STORAGE_FILE, JSON.stringify(localStorageData, null, 2), 'utf-8');
    console.log('[Session] Đã lưu cookie và localStorage thành công.');
  } catch (err) {
    console.warn('[Session] Cảnh báo khi lưu session:', err.message);
  }
}

async function restoreSession(page) {
  if (!fs.existsSync(COOKIE_FILE)) {
    return false;
  }

  try {
    const cookiesData = fs.readFileSync(COOKIE_FILE, 'utf-8');
    const cookies = JSON.parse(cookiesData);
    if (Array.isArray(cookies) && cookies.length > 0) {
      await page.setCookie(...cookies);
      console.log(`[Session] Đã khôi phục ${cookies.length} cookies.`);
    }

    if (fs.existsSync(STORAGE_FILE)) {
      const storageData = JSON.parse(fs.readFileSync(STORAGE_FILE, 'utf-8'));
      await page.evaluateOnNewDocument((data) => {
        for (const [key, value] of Object.entries(data)) {
          localStorage.setItem(key, value);
        }
      }, storageData);
      console.log('[Session] Đã chuẩn bị nạp localStorage state.');
    }

    return true;
  } catch (err) {
    console.warn('[Session] Lỗi khi khôi phục session:', err.message);
    return false;
  }
}

function clearSession() {
  if (fs.existsSync(COOKIE_FILE)) fs.unlinkSync(COOKIE_FILE);
  if (fs.existsSync(STORAGE_FILE)) fs.unlinkSync(STORAGE_FILE);
  console.log('[Session] Đã xoá session cũ.');
}

module.exports = {
  saveSession,
  restoreSession,
  clearSession
};
