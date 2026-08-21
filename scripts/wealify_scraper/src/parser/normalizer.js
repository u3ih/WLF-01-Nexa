/**
 * Chuẩn hoá chuỗi ngày tháng (VD: "20/08/2026 05:45 PM") sang ISO 8601 string
 */
function parseDateTime(dateStr) {
  if (!dateStr) return new Date().toISOString();

  // Đã là ISO format
  if (dateStr.includes('T') || /^\d{4}-\d{2}-\d{2}/.test(dateStr)) {
    return dateStr;
  }

  try {
    // Regex khớp "DD/MM/YYYY HH:MM AM/PM" hoặc "DD/MM/YYYY HH:MM"
    const match = dateStr.match(/(\d{1,2})\/(\d{1,2})\/(\d{4})(?:\s+(\d{1,2}):(\d{2})(?:\s*(AM|PM))?)?/i);
    if (match) {
      const day = parseInt(match[1], 10);
      const month = parseInt(match[2], 10) - 1;
      const year = parseInt(match[3], 10);
      let hour = match[4] ? parseInt(match[4], 10) : 0;
      const minute = match[5] ? parseInt(match[5], 10) : 0;
      const ampm = match[6] ? match[6].toUpperCase() : null;

      if (ampm === 'PM' && hour < 12) hour += 12;
      if (ampm === 'AM' && hour === 12) hour = 0;

      const d = new Date(Date.UTC(year, month, day, hour, minute));
      return d.toISOString();
    }
  } catch (err) {
    // Fallback nếu không parse được
  }

  return dateStr;
}

/**
 * Tách số tiền và loại tiền từ chuỗi (VD: "+250.00 USD", "-18.93 USD", "150,000 VND")
 */
function parseAmount(amountStr) {
  if (typeof amountStr === 'number') {
    return { amount: amountStr, currency: 'USD' };
  }
  if (!amountStr) {
    return { amount: 0, currency: 'USD' };
  }

  const clean = amountStr.replace(/\s+/g, ' ').trim();
  const isNegative = clean.includes('-') || clean.includes('(');
  
  // Lấy đơn vị tiền tệ (USD, VND, EUR, etc.)
  const currencyMatch = clean.match(/[A-Z]{3}|₫|\$/);
  let currency = 'USD';
  if (currencyMatch) {
    if (currencyMatch[0] === '₫') currency = 'VND';
    else if (currencyMatch[0] === '$') currency = 'USD';
    else currency = currencyMatch[0];
  }

  // Lấy giá trị số
  const numberClean = clean.replace(/[^0-9.,]/g, '').replace(/,/g, '');
  let val = parseFloat(numberClean) || 0;
  if (isNegative) val = -Math.abs(val);

  return {
    amount: val,
    currency: currency
  };
}

/**
 * Chuẩn hoá bản ghi giao dịch từ hàng DOM
 */
function normalizeDomRow(rawRow, sidebarDetail = null) {
  const cells = rawRow.rawCells || [];
  
  // Cột 0: Loại (Nạp tiền / Chi tiêu / Rút tiền) & Nguồn (Ví / Thẻ)
  let type = 'Chi tiêu';
  let sourceType = 'Thẻ';
  if (cells[0]) {
    const parts = cells[0].split('\n').map(s => s.trim()).filter(Boolean);
    if (parts[0]) type = parts[0];
    if (parts[1]) sourceType = parts[1];
  }

  // Cột 1: Thẻ (Tên thẻ + Số thẻ xxxx)
  let cardName = '';
  let cardMask = '';
  if (cells[1]) {
    const lines = cells[1].split('\n').map(s => s.trim()).filter(Boolean);
    if (lines[0]) cardName = lines[0];
    const maskMatch = cells[1].match(/(?:[x*]{4}\s*){1,3}(\d{4})/i) || cells[1].match(/\d{4}$/);
    if (maskMatch) cardMask = maskMatch[1] || maskMatch[0];
  }

  // Cột 2: Tham chiếu / Mô tả
  let reference = cells[2] || '';

  // Cột 3: Mã giao dịch
  let txId = rawRow.detectedTxId || cells[3] || `WLF-UNKNOWN-${Date.now()}`;
  txId = txId.replace(/\s+/g, '').replace(/[^\w-]/g, '');

  // Cột 4: Số tiền
  const { amount, currency } = parseAmount(cells[4] || '0');

  // Cột 5: Thời gian tạo
  const createdAt = parseDateTime(cells[5] || '');

  // Cột 6: Trạng thái
  let status = rawRow.status || cells[6] || 'Success';

  // Chuẩn hoá sidebar detail
  const cleanSidebar = {};
  if (sidebarDetail) {
    for (const [k, v] of Object.entries(sidebarDetail)) {
      if (k === 'raw_content') continue;
      const cleanKey = k.toLowerCase().replace(/[^a-z0-9_]/gi, '_');
      cleanSidebar[cleanKey] = v;
    }
  }

  return {
    transaction_id: txId,
    type: type,
    source_type: sourceType,
    card: {
      name: cardName,
      last4: cardMask
    },
    reference: reference,
    amount: amount,
    currency: currency,
    status: status,
    created_at: createdAt,
    sidebar_details: Object.keys(cleanSidebar).length > 0 ? cleanSidebar : (sidebarDetail || {})
  };
}

module.exports = {
  parseDateTime,
  parseAmount,
  normalizeDomRow
};
