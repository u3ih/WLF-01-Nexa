const path = require('path');
const fs = require('fs');
require('dotenv').config({ path: path.join(__dirname, '..', '.env') });

const args = process.argv.slice(2);

function getArg(flags, defaultValue) {
  if (typeof flags === 'string') flags = [flags];
  for (const flag of flags) {
    const idx = args.indexOf(flag);
    if (idx !== -1 && args[idx + 1] && !args[idx + 1].startsWith('--')) {
      return args[idx + 1];
    }
  }
  return defaultValue;
}

function hasArg(flags) {
  if (typeof flags === 'string') flags = [flags];
  return flags.some(flag => args.includes(flag));
}

const config = {
  baseUrl: getArg(['--url', '-u'], process.env.WEALIFY_BASE_URL || 'https://app.wealify.com'),
  username: getArg(['--user', '--username'], process.env.WEALIFY_USERNAME || ''),
  password: getArg(['--pass', '--password'], process.env.WEALIFY_PASSWORD || ''),
  headless: hasArg(['--headless']) 
    ? getArg('--headless', 'true') === 'true'
    : (process.env.WEALIFY_HEADLESS === 'true'),
  outputDir: path.resolve(getArg(['--output', '-o'], process.env.WEALIFY_OUTPUT_DIR || path.join(__dirname, '..', 'output'))),
  sessionDir: path.resolve(path.join(__dirname, '..', 'sessions')),
  pageLimit: parseInt(getArg(['--limit', '-l'], process.env.WEALIFY_PAGE_LIMIT || '0'), 10),
  fullDrawer: hasArg(['--full-drawer'])
    ? getArg('--full-drawer', 'true') === 'true'
    : (process.env.WEALIFY_FULL_DRAWER !== 'false'),
  dateFrom: getArg('--date-from', process.env.WEALIFY_DATE_FROM || ''),
  dateTo: getArg('--date-to', process.env.WEALIFY_DATE_TO || ''),
  otpAuto: hasArg(['--otp-auto'])
    ? true
    : (process.env.WEALIFY_OTP_AUTO === 'true'),
  otpYopmailUser: getArg('--otp-user', process.env.WEALIFY_OTP_YOPMAIL_USER || '')
};

// Đảm bảo thư mục session và output tồn tại
if (!fs.existsSync(config.outputDir)) {
  fs.mkdirSync(config.outputDir, { recursive: true });
}
if (!fs.existsSync(config.sessionDir)) {
  fs.mkdirSync(config.sessionDir, { recursive: true });
}

module.exports = config;
