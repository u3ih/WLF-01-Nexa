class NetworkInterceptor {
  constructor() {
    this.capturedTransactions = new Map();
    this.capturedDetails = new Map();
    this.authHeader = null;
    this.cookies = [];
    this.apiEndpoints = new Set();
  }

  setup(page) {
    console.log('[Interceptor] Đã kích hoạt lắng nghe network traffic...');

    page.on('request', (request) => {
      const headers = request.headers();
      if (headers['authorization'] && !this.authHeader) {
        this.authHeader = headers['authorization'];
        console.log('[Interceptor] 🔑 Bắt được Authorization Token:', this.authHeader.substring(0, 25) + '...');
      }
    });

    page.on('response', async (response) => {
      const url = response.url();
      const status = response.status();
      const contentType = response.headers()['content-type'] || '';

      if (status >= 200 && status < 300 && contentType.includes('application/json')) {
        // Lọc các API liên quan đến giao dịch / thẻ
        if (
          url.includes('transaction') ||
          url.includes('giao-dich') ||
          url.includes('cards') ||
          url.includes('wallet') ||
          url.includes('statement')
        ) {
          this.apiEndpoints.add(url);
          try {
            const data = await response.json();
            this.handleApiResponse(url, data);
          } catch (err) {
            // Không phải JSON parse được hoặc đã bị stream
          }
        }
      }
    });
  }

  handleApiResponse(url, data) {
    // Trích xuất mảng giao dịch nếu API trả về danh sách
    let items = [];
    if (Array.isArray(data)) {
      items = data;
    } else if (data && typeof data === 'object') {
      if (Array.isArray(data.items)) items = data.items;
      else if (Array.isArray(data.data)) items = data.data;
      else if (Array.isArray(data.results)) items = data.results;
      else if (Array.isArray(data.transactions)) items = data.transactions;
      else if (data.id || data.transaction_id || data.code) {
        // Đây có thể là chi tiết của 1 giao dịch đơn lẻ
        const id = data.id || data.transaction_id || data.code || data.m_giao_d_ch;
        this.capturedDetails.set(String(id), data);
        console.log(`[Interceptor] 📦 Bắt được API chi tiết giao dịch: ${id}`);
        return;
      }
    }

    if (items.length > 0) {
      console.log(`[Interceptor] 📦 Bắt được ${items.length} giao dịch từ API endpoint: ${url}`);
      for (const item of items) {
        const id = item.id || item.transaction_id || item.code || item.reference_id || item.m_giao_d_ch;
        if (id) {
          this.capturedTransactions.set(String(id), item);
        }
      }
    }
  }

  getCapturedList() {
    return Array.from(this.capturedTransactions.values());
  }

  getCapturedDetail(id) {
    return this.capturedDetails.get(String(id));
  }
}

module.exports = NetworkInterceptor;
