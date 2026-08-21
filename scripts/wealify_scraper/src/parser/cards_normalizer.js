const { parseDateTime, parseAmount } = require('./normalizer');

function parseNumericMoney(valStr) {
  if (typeof valStr === 'number') return valStr;
  if (!valStr) return 0;
  const clean = String(valStr).replace(/[^0-9.-]/g, '');
  return parseFloat(clean) || 0;
}

function normalizeCardRecord(rawRow, sidebarDetail = null) {
  const cardName = rawRow.cardName || sidebarDetail?.nickname || 'Wealify Card';
  const last4 = rawRow.last4 || (sidebarDetail?.card_number_masked ? sidebarDetail.card_number_masked.slice(-4) : '0000');
  
  // Ưu tiên lấy số dư từ Drawer nếu có, nếu không lấy từ bảng
  let balance = 0;
  if (sidebarDetail && sidebarDetail.balance_detail) {
    balance = parseNumericMoney(sidebarDetail.balance_detail);
  } else if (rawRow.balance) {
    balance = parseNumericMoney(rawRow.balance);
  }

  const totalDeposit = parseNumericMoney(rawRow.totalDeposit || '0');
  const totalWithdrawal = Math.abs(parseNumericMoney(rawRow.totalWithdrawal || '0'));
  
  const createdAtIso = parseDateTime(rawRow.createdAt);
  const status = sidebarDetail?.badge_status || rawRow.status || 'Active';

  return {
    card_id: `CARD_${last4}`,
    card_name: cardName,
    purpose: rawRow.purpose || '',
    last4: last4,
    card_number_masked: sidebarDetail?.card_number_masked || `xxxx xxxx xxxx ${last4}`,
    expiry_date: sidebarDetail?.expiry_date || '',
    cvv: sidebarDetail?.cvv || '***',
    status: status,
    card_network: sidebarDetail?.card_network || 'VISA Platinum Business',
    email: sidebarDetail?.email || '',
    phone: sidebarDetail?.phone || '',
    balance: balance,
    currency: 'USD',
    total_deposit: totalDeposit,
    total_withdrawal: totalWithdrawal,
    created_at: createdAtIso,
    sidebar_details: sidebarDetail || {}
  };
}

module.exports = {
  parseNumericMoney,
  normalizeCardRecord
};
