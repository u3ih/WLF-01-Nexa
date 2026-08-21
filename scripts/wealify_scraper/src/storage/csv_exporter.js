const fs = require('fs');
const path = require('path');

function escapeCsv(val) {
  if (val === null || val === undefined) return '""';
  const str = String(val).replace(/"/g, '""');
  return `"${str}"`;
}

function exportToCsv(transactions, outputDir, filename = 'transactions.csv') {
  const filePath = path.join(outputDir, filename);

  const headers = [
    'transaction_id',
    'created_at',
    'completed_at',
    'type',
    'source_type',
    'card_name',
    'card_last4',
    'reference',
    'amount',
    'user_amount',
    'settled_amount',
    'exchange_rate',
    'currency',
    'status',
    'linked_transaction_id',
    'fee',
    'merchant',
    'mcc',
    'gateway_ref'
  ];

  const rows = [headers.join(',')];

  for (const t of transactions) {
    const sb = t.sidebar_details || {};
    const row = [
      escapeCsv(t.transaction_id),
      escapeCsv(sb.created_at_detail || t.created_at),
      escapeCsv(sb.completed_at || sb.th_nh_c_ng_v_o || ''),
      escapeCsv(sb.transaction_type || t.type),
      escapeCsv(t.source_type),
      escapeCsv(sb.card_name || t.card?.name || ''),
      escapeCsv(sb.card_number || t.card?.last4 || ''),
      escapeCsv(sb.reference || t.reference),
      escapeCsv(t.amount),
      escapeCsv(sb.user_amount || ''),
      escapeCsv(sb.settled_amount || ''),
      escapeCsv(sb.exchange_rate || ''),
      escapeCsv(t.currency),
      escapeCsv(sb.status || t.status),
      escapeCsv(sb.linked_transaction_id || sb.id_giao_d_ch_r_t_v__th_ || ''),
      escapeCsv(sb.fee || ''),
      escapeCsv(sb.merchant || ''),
      escapeCsv(sb.mcc || ''),
      escapeCsv(sb.gateway_ref || '')
    ];
    rows.push(row.join(','));
  }

  fs.writeFileSync(filePath, rows.join('\n'), 'utf-8');
  console.log(`[Export] 📊 Đã lưu ${transactions.length} giao dịch vào file CSV: ${filePath}`);
  return filePath;
}

module.exports = {
  exportToCsv
};
