const fs = require('fs');
const path = require('path');

function exportToJson(transactions, outputDir, filename = 'transactions_full.json') {
  const filePath = path.join(outputDir, filename);

  // Nếu file đã tồn tại, merge theo transaction_id
  let mergedMap = new Map();
  if (fs.existsSync(filePath)) {
    try {
      const existing = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
      if (Array.isArray(existing)) {
        for (const item of existing) {
          if (item.transaction_id) mergedMap.set(item.transaction_id, item);
        }
      }
    } catch (err) {}
  }

  for (const item of transactions) {
    if (item.transaction_id) {
      mergedMap.set(item.transaction_id, item);
    }
  }

  const finalArray = Array.from(mergedMap.values());
  // Sắp xếp theo created_at giảm dần
  finalArray.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));

  fs.writeFileSync(filePath, JSON.stringify(finalArray, null, 2), 'utf-8');
  console.log(`[Export] 💾 Đã lưu ${finalArray.length} giao dịch vào file JSON: ${filePath}`);
  return filePath;
}

module.exports = {
  exportToJson
};
