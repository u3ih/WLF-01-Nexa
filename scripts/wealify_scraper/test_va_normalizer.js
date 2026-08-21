const assert = require('assert');
const { normalizeVaRecord, maskAccountNumber } = require('./src/parser/va_normalizer');
const { exportVaToJson, exportVaToCsv, generateVaSummaryReport } = require('./src/storage/va_exporter');
const path = require('path');
const fs = require('fs');

console.log('--- Testing International Accounts Normalizer with UI Screenshot Data ---');

const mockVaRow = {
  rowIndex: 0,
  accountName: 'ETSY SELLER',
  accountNumber: '9631249900000105835',
  payoutSource: 'Etsy',
  bankName: 'BIDV',
  totalReceived: '1,315,868,000',
  currency: 'VND',
  status: 'Active'
};

const mockVaDrawer = {
  account_name: 'ETSY SELLER',
  account_nickname: 'ETSY SELLER',
  account_number: '9631249900000105835',
  bank_name_full: 'BIDV - JSC Bank for Investment and Development of Vietnam',
  swift_bic: 'BIDVVNVX',
  managed_by: 'Không có người quản lý',
  payout_source: 'Etsy',
  fee: '0%',
  currency: 'VND',
  total_received_detail: '1,315,868,000',
  created_at_detail: '15/02/2026 | 3:00 PM',
  status: 'Active'
};

const normalized = normalizeVaRecord(mockVaRow, mockVaDrawer);

assert.strictEqual(normalized.account_name, 'ETSY SELLER');
assert.strictEqual(normalized.account_number, '9631249900000105835');
assert.strictEqual(normalized.payout_source, 'Etsy');
assert.strictEqual(normalized.bank_name, 'BIDV - JSC Bank for Investment and Development of Vietnam');
assert.strictEqual(normalized.swift_bic, 'BIDVVNVX');
assert.strictEqual(normalized.fee, '0%');
assert.strictEqual(normalized.total_received, 1315868000);
assert.strictEqual(normalized.currency, 'VND');
assert.strictEqual(normalized.status, 'Active');

console.log('✓ International Account Normalizer test passed!');

const testDir = path.join(__dirname, 'test_output_va');
if (!fs.existsSync(testDir)) fs.mkdirSync(testDir, { recursive: true });

exportVaToJson([normalized], testDir, 'test_va.json');
exportVaToCsv([normalized], testDir, 'test_va.csv');
generateVaSummaryReport([normalized], testDir);

assert.ok(fs.existsSync(path.join(testDir, 'test_va.json')));
assert.ok(fs.existsSync(path.join(testDir, 'test_va.csv')));
assert.ok(fs.existsSync(path.join(testDir, 'virtual_accounts_summary_report.md')));

fs.rmSync(testDir, { recursive: true, force: true });
console.log('✓ All International Accounts tests passed successfully!');
