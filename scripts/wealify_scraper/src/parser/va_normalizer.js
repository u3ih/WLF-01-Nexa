const { parseDateTime } = require('./normalizer');
const { parseNumericMoney } = require('./cards_normalizer');

function maskAccountNumber(accNum) {
  if (!accNum) return '';
  if (accNum.includes('•') || accNum.includes('*')) return accNum;
  const len = accNum.length;
  if (len <= 4) return accNum;
  return '••••••' + accNum.slice(-4);
}

function normalizeVaRecord(rawRow, sidebarDetail = null) {
  const accountName = sidebarDetail?.account_name || rawRow.accountName || 'Tài khoản quốc tế';
  const accountNickname = sidebarDetail?.account_nickname || accountName;

  const rawAccNum = sidebarDetail?.account_number || rawRow.accountNumber || '';
  const maskedAccNum = maskAccountNumber(rawAccNum);

  const payoutSource = sidebarDetail?.payout_source || rawRow.payoutSource || '';
  const bankNameFull = sidebarDetail?.bank_name_full || sidebarDetail?.bank_name || rawRow.bankName || '';
  const bankShort = rawRow.bankName || bankNameFull.split('-')[0].trim();

  const swiftBic = sidebarDetail?.swift_bic || '';
  const managedBy = sidebarDetail?.managed_by || 'Không có người quản lý';
  const fee = sidebarDetail?.fee || '0%';

  const currency = sidebarDetail?.currency || rawRow.currency || 'VND';

  // Lấy tổng số tiền nhận được
  let totalReceived = 0;
  if (sidebarDetail && sidebarDetail.total_received_detail) {
    totalReceived = parseNumericMoney(sidebarDetail.total_received_detail);
  } else if (rawRow.totalReceived) {
    totalReceived = parseNumericMoney(rawRow.totalReceived);
  }

  const status = sidebarDetail?.status || rawRow.status || 'Active';
  const createdAtIso = parseDateTime(sidebarDetail?.created_at_detail || rawRow.createdAt);

  return {
    account_name: accountName,
    account_nickname: accountNickname,
    account_number: rawAccNum,
    account_number_masked: maskedAccNum,
    payout_source: payoutSource,
    bank_name: bankNameFull || bankShort,
    bank_short: bankShort,
    swift_bic: swiftBic,
    managed_by: managedBy,
    fee: fee,
    total_received: totalReceived,
    currency: currency,
    status: status,
    created_at: createdAtIso,
    sidebar_details: sidebarDetail || {}
  };
}

module.exports = {
  maskAccountNumber,
  normalizeVaRecord
};
