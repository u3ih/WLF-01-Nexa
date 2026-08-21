const fs = require('fs');
const path = require('path');

function escapeCsv(val) {
  if (val === null || val === undefined) return '""';
  const str = String(val).replace(/"/g, '""');
  return `"${str}"`;
}

function exportCardsToJson(cards, outputDir, filename = 'cards_full.json') {
  const filePath = path.join(outputDir, filename);

  let mergedMap = new Map();
  if (fs.existsSync(filePath)) {
    try {
      const existing = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
      if (Array.isArray(existing)) {
        for (const item of existing) {
          if (item.card_id || item.last4) mergedMap.set(item.card_id || item.last4, item);
        }
      }
    } catch (err) {}
  }

  for (const item of cards) {
    const key = item.card_id || item.last4;
    if (key) mergedMap.set(key, item);
  }

  const finalArray = Array.from(mergedMap.values());
  fs.writeFileSync(filePath, JSON.stringify(finalArray, null, 2), 'utf-8');
  console.log(`[Export] 💾 Đã lưu ${finalArray.length} thẻ ảo vào JSON: ${filePath}`);
  return filePath;
}

function exportCardsToCsv(cards, outputDir, filename = 'cards.csv') {
  const filePath = path.join(outputDir, filename);

  const headers = [
    'card_id',
    'card_name',
    'last4',
    'card_number_masked',
    'expiry_date',
    'status',
    'balance',
    'currency',
    'total_deposit',
    'total_withdrawal',
    'purpose',
    'email',
    'phone',
    'card_network',
    'created_at'
  ];

  const rows = [headers.join(',')];

  for (const c of cards) {
    const row = [
      escapeCsv(c.card_id),
      escapeCsv(c.card_name),
      escapeCsv(c.last4),
      escapeCsv(c.card_number_masked),
      escapeCsv(c.expiry_date),
      escapeCsv(c.status),
      escapeCsv(c.balance),
      escapeCsv(c.currency),
      escapeCsv(c.total_deposit),
      escapeCsv(c.total_withdrawal),
      escapeCsv(c.purpose),
      escapeCsv(c.email),
      escapeCsv(c.phone),
      escapeCsv(c.card_network),
      escapeCsv(c.created_at)
    ];
    rows.push(row.join(','));
  }

  fs.writeFileSync(filePath, rows.join('\n'), 'utf-8');
  console.log(`[Export] 📊 Đã lưu ${cards.length} thẻ ảo vào CSV: ${filePath}`);
  return filePath;
}

function generateCardsSummaryReport(cards, outputDir) {
  let totalBalance = 0;
  let totalDeposits = 0;
  let totalWithdrawals = 0;
  let activeCards = 0;

  for (const c of cards) {
    totalBalance += (c.balance || 0);
    totalDeposits += (c.total_deposit || 0);
    totalWithdrawals += (c.total_withdrawal || 0);
    if (c.status === 'Active') activeCards++;
  }

  const report = [
    '# Báo cáo tổng hợp Thẻ ảo Wealify (Virtual Cards)',
    `*Thời gian tạo: ${new Date().toISOString()}*`,
    '',
    '## 1. Tổng quan số liệu',
    `- **Tổng số thẻ ảo:** ${cards.length}`,
    `- **Số thẻ đang hoạt động:** ${activeCards} / ${cards.length}`,
    `- **Tổng số dư hiện tại:** $${totalBalance.toFixed(2)} USD`,
    `- **Tổng tiền đã nạp vào thẻ:** +$${totalDeposits.toFixed(2)} USD`,
    `- **Tổng tiền đã rút / chi:** -$${totalWithdrawals.toFixed(2)} USD`,
    '',
    '## 2. Danh sách chi tiết từng thẻ',
    '| Tên thẻ | Đuôi thẻ | Mục đích | Số dư | Tổng nạp | Tổng rút | Hạn thẻ | Trạng thái |',
    '|---|---|---|---|---|---|---|---|',
    ...cards.map(c => `| **${c.card_name}** | \`**** ${c.last4}\` | ${c.purpose || '-'} | $${(c.balance || 0).toFixed(2)} | +$${(c.total_deposit || 0).toFixed(2)} | -$${(c.total_withdrawal || 0).toFixed(2)} | ${c.expiry_date || '-'} | \`${c.status}\` |`),
    ''
  ].join('\n');

  fs.writeFileSync(path.join(outputDir, 'cards_summary_report.md'), report, 'utf-8');
}

module.exports = {
  exportCardsToJson,
  exportCardsToCsv,
  generateCardsSummaryReport
};
