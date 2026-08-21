const assert = require('assert');
const { normalizeCardRecord, parseNumericMoney } = require('./src/parser/cards_normalizer');
const { exportCardsToJson, exportCardsToCsv, generateCardsSummaryReport } = require('./src/storage/cards_exporter');
const path = require('path');
const fs = require('fs');

console.log('--- Testing Cards Normalizer with Screenshot Data ---');

const mockCardRow = {
  rowIndex: 3,
  cardName: 'Zenith Main',
  last4: '0003',
  purpose: 'Zenith main',
  balance: '$1,167.86',
  totalDeposit: '+$4,422.58',
  totalWithdrawal: '-$3,850.72',
  createdAt: '08/03/2026 07:00 AM',
  status: 'Active'
};

const mockCardDrawer = {
  nickname: 'Zenith Main',
  email: 'wealifytester@yopmail.com',
  phone: '912345678',
  card_number_masked: '**** **** **** 0003',
  cvv: '***',
  expiry_date: '12/29',
  balance_detail: '1,167.86 USD',
  badge_status: 'Active',
  card_network: 'VISA Platinum Business'
};

const normalizedCard = normalizeCardRecord(mockCardRow, mockCardDrawer);

assert.strictEqual(normalizedCard.card_name, 'Zenith Main');
assert.strictEqual(normalizedCard.last4, '0003');
assert.strictEqual(normalizedCard.balance, 1167.86);
assert.strictEqual(normalizedCard.total_deposit, 4422.58);
assert.strictEqual(normalizedCard.total_withdrawal, 3850.72);
assert.strictEqual(normalizedCard.email, 'wealifytester@yopmail.com');
assert.strictEqual(normalizedCard.phone, '912345678');
assert.strictEqual(normalizedCard.expiry_date, '12/29');
assert.strictEqual(normalizedCard.status, 'Active');

console.log('✓ Card normalization verified successfully!');

const testDir = path.join(__dirname, 'test_output_cards');
if (!fs.existsSync(testDir)) fs.mkdirSync(testDir, { recursive: true });

exportCardsToJson([normalizedCard], testDir, 'test_cards.json');
exportCardsToCsv([normalizedCard], testDir, 'test_cards.csv');
generateCardsSummaryReport([normalizedCard], testDir);

assert.ok(fs.existsSync(path.join(testDir, 'test_cards.json')));
assert.ok(fs.existsSync(path.join(testDir, 'test_cards.csv')));
assert.ok(fs.existsSync(path.join(testDir, 'cards_summary_report.md')));

fs.rmSync(testDir, { recursive: true, force: true });
console.log('✓ All Card Exporter and Normalizer tests passed!');
