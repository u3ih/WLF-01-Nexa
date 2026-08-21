const fs = require('fs');
const path = require('path');

function escapeCsv(val) {
  if (val === null || val === undefined) return '""';
  const str = String(val).replace(/"/g, '""');
  return `"${str}"`;
}

function exportVaToJson(accounts, outputDir, filename = 'virtual_accounts_full.json') {
  const filePath = path.join(outputDir, filename);

  let mergedMap = new Map();
  if (fs.existsSync(filePath)) {
    try {
      const existing = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
      if (Array.isArray(existing)) {
        for (const item of existing) {
          const k = item.account_number || item.account_name;
          if (k) mergedMap.set(k, item);
        }
      }
    } catch (err) {}
  }

  for (const item of accounts) {
    const k = item.account_number || item.account_name;
    if (k) mergedMap.set(k, item);
  }

  const finalArray = Array.from(mergedMap.values());
  fs.writeFileSync(filePath, JSON.stringify(finalArray, null, 2), 'utf-8');
  console.log(`[Export] 💾 Đã lưu ${finalArray.length} Tài khoản quốc tế vào JSON: ${filePath}`);
  return filePath;
}

function exportVaToCsv(accounts, outputDir, filename = 'virtual_accounts.csv') {
  const filePath = path.join(outputDir, filename);

  const headers = [
    'account_name',
    'account_nickname',
    'account_number',
    'account_number_masked',
    'payout_source',
    'bank_name',
    'swift_bic',
    'total_received',
    'currency',
    'fee',
    'status',
    'managed_by',
    'created_at'
  ];

  const rows = [headers.join(',')];

  for (const a of accounts) {
    const row = [
      escapeCsv(a.account_name),
      escapeCsv(a.account_nickname),
      escapeCsv(a.account_number),
      escapeCsv(a.account_number_masked),
      escapeCsv(a.payout_source),
      escapeCsv(a.bank_name),
      escapeCsv(a.swift_bic),
      escapeCsv(a.total_received),
      escapeCsv(a.currency),
      escapeCsv(a.fee),
      escapeCsv(a.status),
      escapeCsv(a.managed_by),
      escapeCsv(a.created_at)
    ];
    rows.push(row.join(','));
  }

  fs.writeFileSync(filePath, rows.join('\n'), 'utf-8');
  console.log(`[Export] 📊 Đã lưu ${accounts.length} Tài khoản quốc tế vào CSV: ${filePath}`);
  return filePath;
}

function generateVaSummaryReport(accounts, outputDir) {
  let totalVnd = 0;
  let totalUsd = 0;
  let activeCount = 0;

  for (const a of accounts) {
    if (a.currency === 'VND') totalVnd += (a.total_received || 0);
    else totalUsd += (a.total_received || 0);

    if (a.status === 'Active') activeCount++;
  }

  const report = [
    '# Báo cáo tổng hợp Tài khoản quốc tế Wealify',
    `*Thời gian tạo: ${new Date().toISOString()}*`,
    '',
    '## 1. Tổng quan số liệu',
    `- **Tổng số tài khoản:** ${accounts.length}`,
    `- **Số tài khoản đang hoạt động:** ${activeCount} / ${accounts.length}`,
    `- **Tổng tiền nhận (VND):** ${totalVnd.toLocaleString('vi-VN')} VND`,
    `- **Tổng tiền nhận (USD):** $${totalUsd.toLocaleString('en-US', { minimumFractionDigits: 2 })} USD`,
    '',
    '## 2. Danh sách chi tiết từng tài khoản',
    '| Tên tài khoản | Số tài khoản | Nguồn rút | Ngân hàng | Tổng tiền nhận | Tiền tệ | Phí | Trạng thái |',
    '|---|---|---|---|---|---|---|---|',
    ...accounts.map(a => `| **${a.account_name}** | \`${a.account_number}\` | ${a.payout_source} | ${a.bank_name} | ${a.total_received.toLocaleString()} | ${a.currency} | ${a.fee} | \`${a.status}\` |`),
    ''
  ].join('\n');

  fs.writeFileSync(path.join(outputDir, 'virtual_accounts_summary_report.md'), report, 'utf-8');
}

module.exports = {
  exportVaToJson,
  exportVaToCsv,
  generateVaSummaryReport
};
