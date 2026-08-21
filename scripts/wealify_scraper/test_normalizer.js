const assert = require('assert');
const { parseDateTime, parseAmount, normalizeDomRow } = require('./src/parser/normalizer');
const { exportToJson } = require('./src/storage/json_exporter');
const { exportToCsv } = require('./src/storage/csv_exporter');
const path = require('path');
const fs = require('fs');

console.log('--- Testing Normalizer with Wealify Sidebar Fields from Screenshot ---');

const mockSidebarWealify = {
  transaction_type: 'Nạp tiền vào ví',
  reference: 'Nạp tiền vào ví từ thẻ ****0001',
  transaction_id: 'TW082026786190',
  linked_transaction_id: 'WLF15-CD-0211',
  card_name: 'Volcano Ads',
  card_number: 'xxxx xxxx xxxx 0001',
  user_amount: '250.00 USD',
  settled_amount: '250.00 USD',
  exchange_rate: '-',
  status: 'Success',
  created_at_detail: '20/08/2026 | 05:46 PM',
  completed_at: '20/08/2026 | 05:46 PM'
};

const mockDomRow = {
  rowIndex: 0,
  rawCells: [
    'Nạp tiền\nVí',
    'Volcano Ads\nxxxx xxxx xxxx 0001',
    'Nạp tiền vào ví từ thẻ ****00...',
    'TW082026786190',
    '+250.00 USD',
    '20/08/2026 05:45 PM',
    'Success'
  ],
  detectedTxId: 'TW082026786190',
  status: 'Success'
};

const result = normalizeDomRow(mockDomRow, mockSidebarWealify);
assert.strictEqual(result.transaction_id, 'TW082026786190');
assert.strictEqual(result.sidebar_details.linked_transaction_id, 'WLF15-CD-0211');
assert.strictEqual(result.sidebar_details.user_amount, '250.00 USD');
assert.strictEqual(result.sidebar_details.completed_at, '20/08/2026 | 05:46 PM');

const testDir = path.join(__dirname, 'test_output');
if (!fs.existsSync(testDir)) fs.mkdirSync(testDir, { recursive: true });

exportToJson([result], testDir, 'test_full.json');
exportToCsv([result], testDir, 'test_full.csv');

assert.ok(fs.existsSync(path.join(testDir, 'test_full.json')));
assert.ok(fs.existsSync(path.join(testDir, 'test_full.csv')));

fs.rmSync(testDir, { recursive: true, force: true });
console.log('✓ All Wealify Sidebar test cases passed successfully!');
