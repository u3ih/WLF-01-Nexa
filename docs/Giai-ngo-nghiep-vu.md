# Giải ngố nghiệp vụ WLF-01
## Tài liệu cho người thuyết trình — không cần biết tài chính từ trước

> Đọc xong cái này bạn sẽ: hiểu người dùng Wealify là ai, tiền của họ đi đường nào,
> vì sao lại có "3 nguồn", và 7 nhiệm vụ của đề bài thực chất giải quyết nỗi đau gì.
> Mọi thuật ngữ đều được giải thích ở lần xuất hiện đầu tiên.

---

## 1. Người dùng của chúng ta là ai

Quên "người dùng ngân hàng" chung chung đi. Hãy hình dung một người cụ thể:

> **Chị Minh Anh, 29 tuổi, Hà Nội.**
> Bán đồ thủ công trên **Etsy**, nhận thêm việc thiết kế trên **Upwork**.
> Doanh thu bằng **đô la Mỹ**. Chi phí chạy quảng cáo Facebook, mua phần mềm,
> trả tiền nhà cung cấp — cũng bằng đô la Mỹ.
> Nhưng chị **sống bằng tiền Việt**, ở Việt Nam, và tiếng Anh chỉ đủ dùng.

Chị không có tài khoản ngân hàng Mỹ theo cách thông thường — người nước ngoài
không tự mở được. **Wealify sinh ra để giải quyết đúng chỗ đó**: cấp cho chị một
tài khoản ngân hàng Mỹ và thẻ để tiêu, trong 24–48 giờ.

Điều đó cũng có nghĩa: chị đột nhiên có một **bản sao kê ngân hàng Mỹ** —
tiếng Anh, đô la Mỹ, tên cửa hàng viết tắt — mà chị chưa từng phải đọc bao giờ.

---

## 2. Mấy cái tên đó là gì

| Tên | Là gì | Vai trò với chị Minh Anh |
|---|---|---|
| **Etsy** | Chợ online của Mỹ chuyên đồ thủ công, đồ cổ, đồ tự làm. Kiểu Shopee nhưng cho đồ handmade, khách chủ yếu Âu–Mỹ | Nơi chị **bán hàng**. Etsy gom tiền khách rồi trả cho chị theo đợt |
| **PayPal** | Ví điện tử quốc tế, phổ biến nhất khi mua bán xuyên biên giới | Một kênh nhận tiền khác |
| **Payoneer / Pingpong / Airwallex** | Các công ty chuyên chuyển tiền xuyên biên giới cho người bán hàng online | Đối thủ / kênh thay thế của Wealify |
| **Upwork** | Sàn việc freelance quốc tế | Nơi chị **nhận việc thiết kế**. Trong dữ liệu mẫu có dòng `UPWORK GLOBAL INC ACH` — đó là tiền công về |
| **Wealify** | Fintech Việt. Cấp tài khoản + thẻ để người Việt nhận và tiêu tiền quốc tế | **Ngân hàng** của chị |

**Điểm mấu chốt:** tất cả những nơi trên đều trả tiền bằng USD, và không nơi nào
chuyển thẳng về ngân hàng Việt Nam một cách rẻ và nhanh. Wealify đứng giữa.

---

## 3. Tiền đi đường nào — luồng đầy đủ

```
   ┌──────────────────────────────────────────────────────────┐
   │  Etsy · PayPal · Upwork      (khách hàng trả tiền)        │
   └────────────────────────┬─────────────────────────────────┘
                            │  ① payout — trả tiền về, bằng USD
                            ▼
   ┌──────────────────────────────────────────────────────────┐
   │  TÀI KHOẢN (Virtual Account)                             │
   │  Sổ cái chính. Ghi mọi khoản vào/ra bằng USD.            │
   │  → sinh ra "SAO KÊ TÀI KHOẢN"                            │
   └───────┬────────────────────────────────┬─────────────────┘
           │ ② nạp thẻ                      │ ③ rút về VN
           ▼                                ▼
   ┌───────────────────┐            ┌──────────────────┐
   │  THẺ (Card)       │            │ Ngân hàng VN     │
   │  Dùng để tiêu:    │            │ (tiền Việt)      │
   │  ads, SaaS, mua   │            └──────────────────┘
   │  → "SAO KÊ THẺ"   │
   └───────────────────┘
           ▲
           │  số dư khả dụng đọc từ
   ┌───────┴───────────┐
   │  VÍ (Wallet)      │
   │  Con số "bạn còn  │
   │  bao nhiêu"       │
   └───────────────────┘
```

**Diễn giải bằng lời:**

1. **Tiền vào** (`payin`): Etsy/Upwork trả USD vào **tài khoản**.
2. **Nạp thẻ** (`transfer_to_card`, còn gọi *top-up*): chị chuyển một phần từ tài
   khoản sang **thẻ** để có tiền tiêu. Tiền **rời tài khoản** rồi mới **lên thẻ**.
3. **Chi tiêu**: quẹt thẻ trả Facebook Ads, Netflix, Spotify…
4. **Rút về Việt Nam** (`payout`): phần còn lại rút về ngân hàng Việt.
5. **Phí** (`fee`): mỗi bước đều có thể bị trừ phí — phí chuyển tiền quốc tế
   (*wire fee*), phí rút ATM, phí đổi tiền.

---

## 4. Vì sao lại có "3 nguồn"? — góc nhìn dân IT

Đây là phần dễ hiểu nhất nếu bạn nghĩ theo kiểu kỹ thuật.

**Ba nguồn = ba hệ thống ghi sổ độc lập, cập nhật không đồng thời.**

| Nguồn | Ai ghi | Ghi cái gì |
|---|---|---|
| **Sao kê tài khoản** | Ngân hàng Mỹ | Tiền vào, tiền ra, phí, lệnh nạp thẻ |
| **Sao kê thẻ** | Tổ chức phát hành thẻ (Visa/Mastercard) | Từng lần quẹt thẻ, từng lần thẻ được nạp |
| **Số dư ví** | Hệ thống Wealify | "Bạn còn bao nhiêu" tại một thời điểm |

Ba hệ thống này **không phải là một**. Chúng đồng bộ với nhau sau một độ trễ —
thực tế nạp thẻ ảo có thể mất **24–48 giờ** mới lên số dư.

> **Nói theo ngôn ngữ IT:** đây là bài toán *eventual consistency* giữa ba
> hệ thống. Bình thường sau vài ngày ba sổ sẽ hội tụ về cùng một sự thật.
> **Đối soát 3 nguồn = kiểm tra xem chúng có thật sự hội tụ không.**
> Bug là khi quá cửa sổ thời gian cho phép mà vẫn lệch.

**Bốn kiểu "không hội tụ" mà đề bài bắt phải bắt được:**

| Triệu chứng | Nghĩa là gì | Người dùng cảm thấy |
|---|---|---|
| **Tiền rời tài khoản chưa lên thẻ** | Tài khoản ghi "-$500", thẻ không ghi "+$500" | "Tiền của tôi biến đâu mất?" |
| **Nạp trùng** | Cùng người gửi, cùng số tiền, cùng ngày, ghi 2 lần | Bấm nạp 2 lần vì lần đầu tưởng lỗi |
| **Phí kép** | Cùng loại phí, cùng ngày, tính 2 lần | Bị trừ oan, không ai báo |
| **Số dư ví lệch** | Số dư đầu kỳ + tổng phát sinh ≠ số dư ví báo | Ba màn hình hiện ba con số |

Nexa **không đoán nguyên nhân** — nó chỉ nói "lệch $38.40, chưa xác định nguyên
nhân". Đây là yêu cầu bắt buộc của đề, và cũng là cách hành xử đúng của một
công cụ kiểm toán.

---

## 5. Từ điển — những từ bạn sẽ phải nói trên sân khấu

### Về dòng tiền

| Thuật ngữ | Nghĩa |
|---|---|
| **Sao kê** (*statement*) | Bảng liệt kê mọi khoản vào/ra trong một kỳ. Ngân hàng phát hành theo tháng |
| **Ngày sao kê** (*statement date*) | Ngày ngân hàng chốt sổ và gửi bảng kê. **Đồng hồ 60 ngày bắt đầu chạy từ đây.** Trong dữ liệu mẫu: 2026-08-05 |
| **Payin / tiền vào** | Tiền chảy vào tài khoản |
| **Payout / tiền ra** | Tiền rút khỏi tài khoản ra ngoài |
| **Transfer to card / nạp thẻ** | Chuyển nội bộ từ tài khoản sang thẻ. Không phải chi tiêu — tiền vẫn của bạn, chỉ đổi chỗ |
| **Fee / phí** | Khoản ngân hàng thu. *Wire fee* = phí chuyển tiền quốc tế (mẫu: $25/lần) |
| **ACH** | Hệ thống chuyển tiền liên ngân hàng của Mỹ. Thấy `ACH` trong descriptor nghĩa là tiền đi qua đường này |
| **Ledger / sổ cái** | Danh sách mọi sự kiện làm thay đổi số dư, theo thứ tự thời gian |

### Về giao dịch thẻ

| Thuật ngữ | Nghĩa |
|---|---|
| **Merchant / người bán** | Nơi nhận tiền khi bạn quẹt thẻ |
| **Descriptor** | Dòng chữ mô tả giao dịch in trên sao kê. **Đây là thủ phạm chính gây khó hiểu** |
| **`SQ *`** | Tiền tố của **Square** — công ty xử lý thanh toán cho quán nhỏ ở Mỹ. `SQ *BLUEBOTTLE COFFEE` = mua cà phê Blue Bottle qua Square |
| **`PP*`** | Tiền tố của **PayPal**. `PP*ZTRDNG LLC 8552` = trả cho một công ty tên ZTRDNG qua PayPal — **và ngay cả biết vậy vẫn không biết ZTRDNG bán gì** |
| **`AMZN MKTP US`** | Amazon Marketplace — mua từ người bán thứ ba trên Amazon |
| **Recurring / định kỳ** | Khoản tự động trừ lặp lại: Netflix, Spotify, iCloud… |
| **Cadence / chu kỳ** | Nhịp lặp: hàng tuần / tháng / quý / năm |

> **Câu chốt cho slide:** người Mỹ nhìn `SQ *` biết ngay là Square.
> Chị Minh Anh thì không. **Đây không phải vấn đề tài chính — đây là vấn đề
> ngôn ngữ và bối cảnh văn hoá.**

### Về khiếu nại — phần quan trọng nhất

| Thuật ngữ | Nghĩa |
|---|---|
| **Dispute / khiếu nại** | Báo ngân hàng "giao dịch này tôi không thực hiện / sai" và yêu cầu xem lại |
| **Chargeback / đòi lại tiền** | Ngân hàng lấy tiền lại từ người bán trả về cho bạn. Đây là kết quả bạn muốn |
| **Cửa sổ 60 ngày** | Theo quy định Mỹ, bạn có **60 ngày kể từ ngày sao kê** để khiếu nại. Quá hạn → ngân hàng **không có nghĩa vụ** xử lý nữa |

**Vì sao đây là slide mạnh nhất của cả bài:**

- Đây là **luật Mỹ**, không phải chính sách Wealify.
- Chị Minh Anh **không có lý do gì để biết nó tồn tại**.
- Đồng hồ chạy **âm thầm** — không ai gửi thông báo nhắc.
- Quá hạn là **mất tiền vĩnh viễn**, không có ngoại lệ.

Trong dữ liệu mẫu: sao kê 2026-08-05 → hạn khiếu nại **2026-10-04**.
Nexa hiện con số này trên **mọi** khoản đáng ngờ.

---

## 6. Bảy nhiệm vụ — dịch sang nỗi đau có thật

### Nhiệm vụ 1 — Đọc & phân loại sao kê
**Kỹ thuật:** tách mỗi dòng vào 5 nhóm: tiền vào · tiền ra · nạp thẻ · phí · chi tiêu.
**Nỗi đau:** sao kê là một danh sách phẳng trộn lẫn tất cả. Không phân loại thì
không trả lời nổi câu "tháng này tôi thực sự tiêu bao nhiêu" — vì *nạp thẻ*
trông giống *tiêu tiền* nhưng không phải.
**Nói trên sân khấu:** *"Chuyển tiền sang thẻ không phải là tiêu tiền. Nếu đếm
nhầm, con số chi tiêu sẽ sai gấp đôi."*

### Nhiệm vụ 2 — Đối soát với email
**Kỹ thuật:** ghép mỗi giao dịch với email biên lai tương ứng → gắn *có email khớp
/ không tìm thấy email / email nghi giả*.
**Nỗi đau:** mỗi lần mua đều có email xác nhận. Không có email = đáng ngờ.
Nhưng nguy hiểm hơn là chiều ngược lại — **email giả mạo**.
**Ví dụ trong dữ liệu mẫu:** một email ký tên "Netflix Billing" nhưng gửi từ
`netfl1x-billing.com` — chữ **i** bị thay bằng **số 1**. Đòi $89.99 mà **không có
giao dịch nào khớp số tiền đó**. Đây là lừa đảo, và Nexa bắt được.
**Nói trên sân khấu:** đây là ví dụ đắt nhất để chiếu lên màn hình.

### Nhiệm vụ 3 — Đối chiếu 3 nguồn
Đã giải thích ở mục 4.
**Nói trên sân khấu:** *"Ba hệ thống, ba sổ ghi. Chúng tôi kiểm tra xem ba sổ có
kể cùng một câu chuyện không."*

### Nhiệm vụ 4 — Bắt bất thường & gói "quên huỷ"
**Kỹ thuật:** ≥3 lần trừ cùng một nơi, khoảng cách đều nhau → là gói định kỳ.
Cùng nơi + cùng số tiền + cách nhau vài phút → tính trùng.
**Nỗi đau:** "gói quên huỷ" là gói vẫn bị trừ tiền đều nhưng **đã ngừng dùng**.
Dấu hiệu nhận biết trong dữ liệu: các kỳ gần đây **không còn email biên lai** —
người dùng đã bỏ theo dõi từ lâu.
**Ví dụ mẫu:** Chegg Study $19.95/tháng, **7 kỳ liên tiếp không có email nào**,
tổng $139.65 đã trôi đi.

### Nhiệm vụ 5 — Gắn nhãn & nhắc hạn
**Ba nhãn, không có nhãn thứ tư:**

| Nhãn | Dùng khi | Ví dụ |
|---|---|---|
| **Định kỳ đã xác định** | Dữ liệu tự chứng minh được | Netflix trừ đều 6 tháng liền |
| **Cần bạn tự xác nhận** | Phụ thuộc ý định người dùng, máy không biết | Mua 2 lần cách nhau 94 giây — cố ý hay lỗi? |
| **Chưa đủ dữ liệu** | Dữ liệu không kết luận được | Chỉ mới trừ 2 lần, chưa đủ gọi là định kỳ |

**Nói trên sân khấu:** *"Không có nhãn 'gian lận'. Chúng tôi không có quyền
tuyên bố điều đó — chỉ toà và ngân hàng mới có."*

### Nhiệm vụ 6 — Báo cáo tài chính
**Kỹ thuật:** tổng chi theo tháng/quý/năm · dự báo ngày trừ tiếp theo · tổng chi
cả năm cho các gói · phát hiện **tăng giá âm thầm**.
**Nỗi đau:** Netflix tăng từ $15.49 lên $17.99 ngày 16/05. Chênh $2.50/tháng —
nhỏ đến mức không ai để ý, nhưng **$30/năm**. Nhân với 5 gói thì thành khoản thật.
**Nói trên sân khấu:** *"$2.50 không đáng để ý. $30 một năm thì có. Và nếu quy ra
tiền Việt là 780.000 đồng — lúc đó mới thấy xót."*

### Nhiệm vụ 7 — Cảnh báo chủ động có kiểm soát
Ba phần: **gửi báo cáo về email của chính người dùng** (phải xác nhận trước) ·
**tạo nhắc hạn** trước khi hết 60 ngày · **chạy rà soát định kỳ mà không báo trùng**.

**Vì sao "không báo trùng" là tiêu chí chấm riêng:** một hệ thống cảnh báo mà
ngày nào cũng báo lại đúng 15 khoản cũ thì người dùng sẽ tắt thông báo sau 3 ngày,
và tất cả công sức thành vô nghĩa. Nexa gán mỗi cảnh báo một **fingerprint** ổn
định, đã báo rồi thì lần sau bỏ qua.

---

## 7. Dữ liệu mẫu có gì — để bạn nói đúng số

**15 phát hiện phải bắt được:**

- **5 gói định kỳ:** T-Mobile $65 · Chegg $19.95 · Netflix $17.99 · Spotify $11.99 · iCloud+ $9.99
- **1 gói quên huỷ:** Chegg, 7 kỳ không email
- **1 tăng giá âm thầm:** Netflix $15.49 → $17.99 ngày 2026-05-16
- **1 mua trùng:** Blue Bottle $6.75 hai lần cách nhau **94 giây**
- **1 phí kép:** phí wire $25 hai lần trong ngày 2026-06-25
- **1 nạp trùng:** $1.200 hai lần ngày 2026-06-03
- **1 tiền chưa lên thẻ:** $500 ngày 2026-07-22
- **1 ví lệch:** $38.40
- **1 cửa hàng không xác định:** `PP*ZTRDNG LLC 8552`
- **1 thiếu biên lai:** `AMZN MKTP US*2K91` $248.13
- **1 email giả mạo:** `netfl1x-billing.com`

**4 trường hợp phải KHÔNG báo** *(đây mới là chỗ ăn điểm)*:

| Trường hợp | Vì sao không báo |
|---|---|
| Starbucks $5.25 hai lần, cách **6,5 tiếng** | Sáng một ly, chiều một ly. Bình thường |
| Whole Foods $64.20 hai lần, cách **46 ngày** | Đi siêu thị hai lần, tiện mua giống nhau |
| Coursera mới trừ **2 lần** | Chưa đủ 3 lần để gọi là định kỳ |
| Phí ATM cùng ngày với phí wire bị kép | **Khác loại phí** — không phải phí kép |

> **Đây là slide phân biệt nhóm mình với các nhóm khác.** Ai cũng khoe "bắt được
> 15 lỗi". Rất ít nhóm chứng minh được **mình không báo bừa**. Một trợ lý báo
> nhầm vài lần là người dùng mất niềm tin và bỏ luôn.

---

## 8. Giám khảo có thể hỏi gì

**"Sao không để AI tự tìm các khoản bất thường?"**
> Vì đề chấm trên đáp án chuẩn. Nếu để mô hình tự tìm, mỗi lần chạy ra một kết
> quả khác nhau. Chúng tôi tách đôi: **máy tất định phát hiện, mô hình diễn giải**.
> Con số luôn giống nhau và unit-test được — hiện có 108 test tự động.

**"Làm sao chứng minh nó không tự chuyển tiền được?"**
> Trong mã nguồn **không tồn tại hàm nào** chuyển tiền, huỷ gói hay khoá thẻ.
> Mô hình chỉ gọi được 14 hàm, tất cả đều chỉ đọc. Không phải mô hình được dặn
> đừng làm — mà là **không có gì để gọi**.
> *(Rồi mở tab "Ranh giới an toàn", mời giám khảo bấm thử.)*

**"Nếu mô hình bịa một con số thì sao?"**
> Mọi con số mô hình viết ra đều bị đối chiếu ngược với kết quả của máy phân
> tích. Sai thì bắt viết lại; vẫn sai thì thay bằng câu của máy. Giao diện hiện
> badge *"số bị loại"* khi cơ chế này bắt được.

**"Vì sao không có màu xanh lá?"**
> Xanh lá nghĩa là "an toàn, không cần làm gì". Trợ lý này **bị cấm** nói tài
> khoản an toàn. Nên trong bảng màu **không có màu xanh lá** — kể cả khi không
> tìm thấy vấn đề gì.

**"Không có mô hình thì sao?"**
> Vẫn trả lời được, bằng máy phân tích, cả tiếng Việt và tiếng Anh. Mô hình chỉ
> làm cho câu chữ mượt hơn.

---

## 9. Những câu TUYỆT ĐỐI không được nói

| ❌ Không nói | ✅ Nói thay bằng |
|---|---|
| "Tài khoản của bạn an toàn" | "Đây là những gì tôi rà soát được, và đây là những gì chưa đủ dữ liệu" |
| "Không có gì bất thường" | "Với dữ liệu hiện có, tôi chưa gắn cờ khoản nào theo tiêu chí này" |
| "Đây chắc chắn là gian lận" | "Khoản này cần bạn tự xác nhận" |
| "Chúng tôi sẽ huỷ gói giúp bạn" | "Tôi soạn sẵn các bước để bạn tự huỷ" |
| "AI của chúng tôi tự phát hiện bất thường" | "Máy phân tích tất định phát hiện, AI diễn giải" |

Ba câu đầu **nằm thẳng trong mục trừ điểm nặng của đề bài**. Câu cuối không sai
luật nhưng làm yếu chính điểm mạnh nhất của nhóm.

---

*Tài liệu nội bộ đội — dùng kèm `docs/WLF-01_Ke_hoach_lam_viec.md` và `docs/DESIGN.md`*
