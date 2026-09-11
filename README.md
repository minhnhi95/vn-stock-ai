# VN Stock AI Analyzer

Công cụ giúp người **chưa rành chứng khoán** theo dõi thị trường Việt Nam: bộ lọc
an toàn, chỉ số cơ bản giải thích bằng tiếng Việt đời thường, bản tin sáng, và
quản lý danh mục thật từ sao kê công ty chứng khoán.

- **Frontend**: React 19 + Vite + lightweight-charts (mobile-first, có PWA)
- **Backend**: FastAPI + [vnstock](https://vnstocks.com)
- **Database**: SQLite khi dev, Postgres (Neon) khi deploy

Nguyên tắc thiết kế, áp dụng ở mọi tính năng:

1. **Python tính mọi con số, AI chỉ diễn đạt lại.** Khi kết quả sai, biết ngay là
   sai ở tầng dữ liệu hay tầng ngôn ngữ.
2. **Kết luận từ quy tắc, không từ AI.** App đưa kết luận "Có thể cân nhắc mua / Chờ
   thêm / Không nên mua", nhưng tính bằng quy tắc Python công khai (`verdict_engine.py`),
   kèm từng tiêu chí đạt/trượt và tỷ lệ quy tắc từng đúng trong quá khứ với chính mã
   đó — so với tỷ lệ của mọi phiên, để thấy quy tắc có thêm được gì không. AI chỉ diễn
   giải số liệu; câu khuyên mua/bán do AI tự viết bị lọc (`verdict_guard.py`), vì không
   ai kiểm chứng được nó.
3. **Thiếu dữ liệu KHÁC với an toàn.** Mọi chỗ không đủ số liệu đều hiện "thiếu
   dữ liệu", không âm thầm tính là "đạt".

> ⚠️ Kết luận của app đến từ quy tắc cố định và có thể sai. Đây không phải lời khuyên
> của chuyên gia tư vấn đầu tư có giấy phép, và app không đặt lệnh. Mọi quyết định mua
> bán là của bạn.

---

## Chạy local

Yêu cầu: Python 3.11+, Node 18+.

```bash
# Backend
cd backend
python -m venv ../.venv
../.venv/Scripts/pip install -r requirements.txt
../.venv/Scripts/python main.py          # http://127.0.0.1:8765
```

```bash
# Frontend
cd frontend
npm install
npm run dev                              # http://localhost:5273
```

Trên Windows có thể chạy cả hai bằng `.\start_servers.bat`. Trong PowerShell phải có
`.\` ở đầu — PowerShell không chạy file ở thư mục hiện tại nếu thiếu nó.

### Mở trên điện thoại

```powershell
.\start_servers.bat lan
```

Rồi mở trên điện thoại cùng mạng địa chỉ mà script in ra, dạng `http://<IPv4>:5273`.
Không cần cấu hình gì thêm: frontend tự gọi API về chính máy đang phục vụ trang, còn
khi chạy local thì backend cho phép mọi địa chỉ mạng nội bộ (10.x, 172.16–31.x,
192.168.x, Tailscale 100.64–127.x). Đổi Wi-Fi, hay hotspot cấp IP mới, cũng không phải
sửa file nào.

Mặc định (không có `lan`) server chỉ nghe trên máy này. Chế độ `lan` cho **mọi thiết bị
cùng mạng** mở được app — kể cả danh mục thật của bạn — nên chỉ dùng ở Wi-Fi nhà hoặc
hotspot của chính bạn, không dùng ở Wi-Fi công cộng.

### Dùng khi ra ngoài, ở mạng khác

Dùng Tailscale — máy này và điện thoại đã ở chung một mạng Tailscale:

```powershell
.\start_servers.bat tailscale
```

Bật app Tailscale trên điện thoại, rồi mở địa chỉ script in ra, dạng
`http://100.x.x.x:5273`. Địa chỉ này cố định cho máy này dù bạn đổi sang mạng nào.
Điện thoại dùng 4G hay Wi-Fi nào cũng được.

Khác với chế độ `lan`: server **chỉ** nghe trên địa chỉ Tailscale. Dù laptop đang bắt
Wi-Fi quán cà phê, người cùng mạng đó cũng không vào được — chỉ thiết bị đăng nhập tài
khoản Tailscale của bạn mới vào được. Tailscale chưa kết nối thì script dừng hẳn, không
tự chuyển sang mở toàn mạng. Ở chế độ này, mở `localhost` ngay trên máy cũng không được;
dùng luôn địa chỉ Tailscale.

Muốn để laptop ở nhà và chỉ mang điện thoại: chạy lệnh trên trước khi đi, cắm sạc, và
chỉnh Windows để máy không ngủ khi cắm điện (Settings → System → Power). Máy ngủ là mất
kết nối.

Chưa nên đưa app lên cloud (Vercel/Railway theo `DEPLOY.md`) để dùng thay: app chưa có
đăng nhập, ai có đường link đều xem được danh mục thật của bạn.

Hai cổng phải khớp nhau, đổi một chỗ thì đổi cả hai:

| Thành phần | Cổng | Khai báo ở |
| --- | --- | --- |
| Backend | 8765 | `start_servers.bat`, `frontend/src/App.jsx` (`resolveApiBase`) |
| Frontend dev server | 5273 | `frontend/vite.config.js`, `start_servers.bat` |

`VITE_API_BASE` chỉ cần khi backend nằm ở máy hoặc cổng khác (production đặt qua
Vercel). Đặt `CORS_ORIGINS` thì backend dùng đúng danh sách đó và tắt quy tắc mạng
nội bộ — production luôn phải đặt.

### Lãi tiết kiệm dùng để so với cổ tức

Phần giải thích lợi suất cổ tức có đối chiếu với lãi gửi tiết kiệm 12 tháng — mặc định
**5,0%/năm** (nhóm ngân hàng lớn, cập nhật 2026). Đây là con số duy nhất trong
`metric_explainer.py` không đến từ báo cáo tài chính, nên cũng là con số duy nhất sẽ cũ
đi. Đổi bằng biến môi trường, không cần sửa code:

```bash
SAVINGS_RATE_PCT=6.2      # trong backend/.env
```

Giá trị vô lý (âm, 0, hoặc ≥ 100) bị bỏ qua và quay về mặc định.

### Gemini API key

Không bắt buộc để xem biểu đồ và chỉ số. Muốn dùng phân tích AI thì nhập key ngay
trên UI (nút *Cấu hình API Key*, lưu ở `localStorage`), hoặc đặt `GEMINI_API_KEY`
trong `backend/.env` để dùng chung cho server. Lấy key tại
[Google AI Studio](https://aistudio.google.com/apikey).

Xem `backend/.env.example` và `frontend/.env.example` cho các biến còn lại.

---

## Test

```bash
cd backend
../.venv/Scripts/pip install -r requirements-dev.txt
../.venv/Scripts/python -m pytest
```

Test không gọi mạng thật (vnstock free tier giới hạn 20 request/phút) và chạy trên
SQLite tạm, không đụng `data.db`. Phạm vi phủ: trạng thái phiên giao dịch, chuẩn hoá
chỉ số cơ bản, chỉ báo kỹ thuật, bộ lọc an toàn, câu giải thích chỉ số + so sánh
ngành, parser giao dịch nội bộ / lịch sự kiện / khối ngoại, đọc sao kê công ty chứng
khoán, FIFO + phí + thuế của danh mục thật, tìm kiếm mã, cảnh báo (CRUD + từng điều
kiện kích hoạt), và validate của các route HTTP.

Lint frontend:

```bash
cd frontend && npm run lint
```

---

## Tính năng

| Nhóm | Mô tả |
| --- | --- |
| Biểu đồ | 3 khung đồng bộ: nến + EMA20/50/200 + khối lượng, RSI(14) có mốc 30/70, MACD; crosshair chung, ô đọc OHLC theo con trỏ; giá cập nhật 5s trong phiên |
| **Kết luận mua / không mua** | "Có thể cân nhắc mua / Chờ thêm / Không nên mua" cho mã đang xem, từ quy tắc công khai: an toàn, xu hướng (EMA50/EMA200, RSI), định giá và sinh lời so với ngành. Kèm từng tiêu chí đạt/trượt và tỷ lệ quy tắc từng đúng 20 phiên sau trong 2 năm qua, so với mọi phiên |
| **Kiểm tra an toàn** | 6 tiêu chí ngưỡng cứng (thanh khoản, thị giá, nợ/vốn chủ, ROE, biên độ, rổ VN100). Chỉ chặn mã rủi ro, **không** gợi ý mã tốt. Quét được nhiều mã một lượt |
| **Cơ bản có giải thích** | 13 chỉ số, mỗi chỉ số kèm một câu tiếng Việt đời thường ("Bạn trả 15,53 đồng để mua 1 đồng lợi nhuận mỗi năm"), trung vị cùng ngành để đối chiếu, và trường hợp con số đó đánh lừa |
| Tin tức | Tin theo mã + tìm kiếm ngữ nghĩa |
| AI giải thích | Đọc giúp chỉ báo kỹ thuật, chỉ số cơ bản, tin tức và khối ngoại của một mã bằng tiếng Việt: dữ liệu nói gì, chỗ nào mâu thuẫn, rủi ro, câu hỏi để tự trả lời. **Không** nhãn MUA/BÁN, độ tin cậy hay giá mục tiêu; câu mang tính chỉ dẫn bị lọc (`verdict_guard.py`) |
| **Danh mục thật** | Nhập sao kê CSV từ công ty chứng khoán → vị thế, giá vốn FIFO, lãi/lỗ **đã trừ phí và thuế TNCN 0,1%**, thống kê chi phí giao dịch |
| Khối ngoại | Mua/bán ròng theo mã (khối lượng + VND) và xếp hạng toàn VN100 |
| Toàn cảnh thị trường | Heatmap ngành theo mã đại diện VN100, khối ngoại mua/bán ròng |
| Theo dõi | Cảnh báo giá / RSI / EMA cắt / **có tin mới**, tự kiểm tra + thông báo trình duyệt; một nút bật báo tin cho toàn bộ danh mục thật; lịch sự kiện; giao dịch nội bộ |
| **Bản tin sáng** | Job nền dùng Antigravity CLI viết bản tin tiếng Việt: chuyện gì xảy ra, **thị trường đã phản ánh chưa**, điều gì làm nhận định sai. Không chấm điểm, không khuyến nghị mua/bán |
| Tìm kiếm | Toàn bộ ~1.700 mã niêm yết theo mã, tên doanh nghiệp hoặc ngành; không dấu vẫn khớp |

---

## Bản tin sáng (Antigravity CLI)

App **không gọi AI lúc phục vụ request**. Một job chạy nền trên máy bạn sinh bản
tin rồi ghi vào DB; web chỉ đọc lại. Nhờ vậy mở app là có ngay, và bản deploy
không cần API key nào.

```bash
cd backend
../.venv/Scripts/python.exe -m jobs.daily_brief            # sinh + lưu
../.venv/Scripts/python.exe -m jobs.daily_brief --dry-run  # chỉ xem dữ liệu đầu vào
```

Chạy tự động mỗi sáng: Task Scheduler → Daily 06:30 → trỏ tới `run_daily_brief.bat`.

**Vì sao là CLI chứ không phải API key** (đo thực tế 2026-09):

| | Antigravity CLI | Gemini API key |
| --- | --- | --- |
| Model | Gemini 3.8 Flash + **Claude Opus 4.6** | chỉ Gemini |
| Thời gian mỗi lần | ~52-60 giây | ~1-3 giây |
| Token nạp mỗi lần | ~23.000 (system prompt của agent) | vài trăm |
| Deploy lên server | không (OAuth cá nhân trong keyring) | được |

Hai con số giữa là lý do job chạy nền chứ không gọi trực tiếp: quá chậm và quá
tốn để gọi mỗi lần người dùng mở app, nhưng hoàn toàn ổn cho ~1 lần/ngày.

**Ranh giới AI/không-AI.** Mọi con số (giá, %, khối lượng, vĩ mô) do Python tính
và đưa vào prompt; AI chỉ diễn đạt lại. Khi bản tin sai, ta biết ngay sai ở tầng
dữ liệu hay tầng diễn đạt. Schema output cố ý KHÔNG có trường điểm số hay
mua/bán — người đọc mục tiêu là nhà đầu tư mới, một chữ "NÊN MUA" với họ là mệnh
lệnh, còn đoạn giải thích thì dạy họ cách tự nghĩ.

**"Thị trường đã biết chưa"** (`jobs/price_reaction.py`) là phép tính thuần, không
qua AI: giá chạy bao nhiêu % trước/sau mốc tin, khối lượng gấp mấy lần mức nền
TRƯỚC cửa sổ đo. Mốc phải lấy trước cửa sổ — lấy trung bình 20 phiên gần nhất thì
chính mấy phiên đột biến tự kéo mốc lên và một cú tăng 2,5× chỉ hiện ra thành 1,1×.

---


**Chạy tự động.** Task Scheduler có sẵn task **"VN Stock - Ban tin sang"**, chạy 07:30 từ
thứ Hai đến thứ Sáu (`run_daily_brief.bat auto`). Khi chạy theo lịch, mọi output ghi vào
`backend/logs/daily_brief.log` — mở file này đầu tiên khi bản tin sáng không cập nhật.
Mỗi lần chạy bị giới hạn 25 phút; quá thì job dừng và in ra đúng dòng code đang kẹt.

**Khi log báo "Antigravity không trả lời (0 token, 0 lượt)".** agy vẫn chạy nhưng yêu cầu
không tới được mô hình — thường là app Antigravity chưa mở hoặc phiên đăng nhập đã hết hạn.
Mở app Antigravity, đăng nhập lại, rồi chạy thử bằng tay:

```powershell
.\run_daily_brief.bat
```
## Trung vị ngành cho phần "Cơ bản"

Panel cơ bản so từng chỉ số với trung vị ngành ICB. Bảng trung vị **không tính lúc
người dùng bấm** — muốn biết P/E trung bình ngành Công nghệ phải lấy chỉ số của cả
ngành, mà vnstock chỉ cho 20 request/phút. Một job chạy nền sinh sẵn bảng đó:

```bash
cd backend
python -m jobs.sector_benchmarks                  # 19 ngành, ~237 mã, ~16 phút
python -m jobs.sector_benchmarks --universe vn100 # nhanh hơn, chỉ đủ 7 ngành
python -m jobs.sector_benchmarks --dry-run        # in ra, không ghi đè
```

Trên Windows đã có sẵn task tự động **"VN Stock - Trung vi nganh"** chạy 07:00 mỗi
Chủ nhật (`run_sector_benchmarks.bat`). Xem hoặc sửa:

```powershell
Get-ScheduledTaskInfo -TaskName "VN Stock - Trung vi nganh"   # lần chạy kế tiếp
Start-ScheduledTask   -TaskName "VN Stock - Trung vi nganh"   # chạy ngay
Unregister-ScheduledTask -TaskName "VN Stock - Trung vi nganh" -Confirm:$false
```

`Stop-ScheduledTask` chỉ dừng `cmd.exe` — tiến trình Python đang quét **vẫn chạy tiếp**
và ghi bảng khi xong. Muốn dừng hẳn:

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object CommandLine -match 'sector_benchmarks' |
  ForEach-Object { Stop-Process -Id $_.ProcessId }
```

Task truyền tham số `auto` cho file .bat. Bắt buộc phải có: khi chạy tay mà job lỗi,
.bat dừng màn hình để đọc thông báo, nhưng dưới Task Scheduler thì `pause` sẽ treo vô
hạn trong một cửa sổ cmd ẩn và lần chạy tuần sau bị bỏ qua vì task cũ chưa kết thúc.
`run_daily_brief.bat` cũng vậy.

Kết quả ghi vào `backend/data/sector_benchmarks.json` và **được commit kèm mã nguồn** —
là dữ liệu tham chiếu chỉ-đọc nên deploy đi đâu cũng có sẵn, không cần migration.
Chỉ số cơ bản đổi mỗi quý, chạy lại hàng tuần là thừa.

Vài lựa chọn có chủ đích:

- **Trung vị, không phải trung bình.** Một mã P/E 400 vì lợi nhuận sắp về 0 sẽ kéo lệch
  trung bình cả ngành.
- **Chọn theo thanh khoản, không lấy bừa.** Ngành Xây dựng có 396 mã niêm yết; trung vị
  dựng từ 12 mã penny không mô tả phần thị trường mà người dùng thật sự mua được.
  `price_board` xếp hạng cả ngành trong một request. Mã không khớp lệnh nào bị loại hẳn,
  và ngành nào `price_board` vẫn không trả được sau khi thử lại thì chỉ dùng mã VN100
  (job in `CANH BAO`) — không bao giờ lấp chỗ trống theo thứ tự ABC. Bảng đầu tiên dính
  đúng lỗi này: ngành Hàng cá nhân & Gia dụng thành A32, AAT, ADS, BBT… thay vì PNJ.
- **Ngành dưới 5 mã có số liệu thì không ghi.** Thà không so còn hơn so với trung vị
  dựng từ 2 mã. UI khi đó chỉ hiện phần giải thích, bỏ phần đối chiếu.
- **Bỏ mã có số liệu quá cũ.** Nhiều mã nhỏ ngừng công bố từ 2019-2020 nhưng nguồn vẫn
  trả kỳ cuối cùng đó; gộp một P/E năm 2019 vào trung vị năm nay là so cổ phiếu hôm nay
  với mặt bằng lãi suất của bảy năm trước.
- **Quét hỏng không được ghi đè.** Mất mạng hay sai interpreter cũng chạy hết vòng lặp và
  cho ra bảng rỗng; job từ chối ghi và giữ nguyên bảng cũ.

---

## Quản lý giao dịch thật

App **không kết nối tới tài khoản chứng khoán hay ngân hàng** và không đặt lệnh hộ.
Nó chỉ ghi nhận những lệnh đã khớp để tính lãi/lỗ cho đúng.

Cách dùng:
1. Vào app/web công ty chứng khoán, xuất lịch sử giao dịch ra **CSV**.
2. Panel "Danh mục thật" → *Nhập sao kê CSV*. Parser tự dò cột nên không cần
   sửa file; dòng nào không đọc được sẽ được liệt kê kèm lý do thay vì bỏ im lặng.
3. Nhập lại file trùng kỳ cũng không sinh bản ghi trùng (khoá theo ngày + mã +
   loại lệnh + khối lượng + giá).

Vì sao không gọi API công ty chứng khoán: ngân hàng VN không có open banking cho
khách cá nhân, còn API môi giới (DNSE EntradeX, SSI FastConnect...) đòi tự đăng ký
và giữ khoá bí mật. Nếu muốn dùng, khoá đó thuộc về bạn và nằm trong `backend/.env`
trên máy bạn — đừng đưa cho bất kỳ ai, kể cả trợ lý AI.

**Lãi/lỗ tính đúng tiền về tài khoản**, không phải chênh lệch giá:
- Phí mua được cộng vào giá vốn.
- Lãi/lỗ chưa chốt đã trừ trước phí bán + thuế TNCN 0,1% nếu bán ngay hôm nay.
- Bán khớp theo **FIFO** — đúng cách công ty chứng khoán và cơ quan thuế ghi nhận.

Mặc định phí môi giới 0,15%/lệnh khi file sao kê không tách cột phí; sửa
`DEFAULT_BROKER_FEE_RATE` trong `broker_import_service.py` cho khớp gói phí của bạn.

> ⚠️ Khuyến nghị AI trong app là mô hình ngôn ngữ đọc chỉ báo kỹ thuật, **chưa có
> bằng chứng nào cho thấy nó sinh lời**. Giá trị thật của app nằm ở chỗ cho bạn
> thấy đúng lãi/lỗ sau chi phí và mức tập trung rủi ro — không phải ở tín hiệu mua bán.

---

## Cấu trúc

```
backend/
  main.py                     # FastAPI app + toàn bộ route
  vnstock_safe.py             # bootstrap: UTF-8 console + chặn sys.exit của vnstock
  stock_service.py            # tải dữ liệu giá + tính chỉ báo
  market_service.py           # phiên giao dịch, giá realtime, chỉ số cơ bản
  ai_service.py               # AI giải thích một mã (không nhãn mua/bán)
  gemini_client.py            # nơi duy nhất gọi Gemini (đổi SDK chỉ sửa file này)
  verdict_guard.py            # lọc câu mang tính chỉ dẫn mua/bán khỏi mọi văn bản AI
  storage_service.py          # cảnh báo + giao dịch thật + bản tin (SQLite / Postgres)
  safety_screen.py            # 6 tiêu chí ngưỡng cứng chặn mã rủi ro cho người mới
  verdict_engine.py           # kết luận mua/chờ/không mua từ quy tắc + tỷ lệ đúng quá khứ
  metric_explainer.py         # dịch chỉ số cơ bản sang tiếng Việt + so trung vị ngành
  market_universe.py          # rổ VN30/VN100 tĩnh làm fallback
  symbol_utils.py             # nhận dạng mã CK VN (nguồn sự thật duy nhất)
  ssl_bootstrap.py            # vá CA bundle khi đường dẫn có dấu tiếng Việt
  jobs/antigravity_client.py  # gọi agy --print, ép output theo JSON schema
  jobs/macro_context.py       # USD/VND, lợi suất Mỹ, dầu Brent, S&P 500
  jobs/price_reaction.py      # đo "thị trường đã phản ánh tin chưa"
  jobs/daily_brief.py         # ghép tất cả -> bản tin, lưu vào DB
  jobs/sector_benchmarks.py   # trung vị chỉ số theo ngành -> data/sector_benchmarks.json
  data/sector_benchmarks.json # bảng tham chiếu, đi kèm mã nguồn (chỉ đọc lúc chạy)
  search_service.py           # index mã niêm yết cho ô tìm kiếm
  broker_import_service.py    # parse sao kê CSV của công ty chứng khoán
  real_portfolio_service.py   # FIFO + phí + thuế -> lãi/lỗ danh mục thật
  news_service.py  foreign_service.py  sector_service.py
  alerts_service.py  calendar_service.py  insider_service.py
  portfolio_review_service.py  multitimeframe_service.py
  tests/                      # pytest
frontend/
  src/App.jsx                 # shell + state chính
  src/components/             # panel theo tính năng
  src/components/StockChart.jsx   # biểu đồ 3 khung (giá+KL, RSI, MACD)
  src/components/ErrorBoundary.jsx # cô lập lỗi render theo từng panel
  src/hooks/useModalDismiss.js     # Escape đóng modal + khoá cuộn nền
  scripts/generate_icons.py   # sinh icon PWA từ public/icon.svg
  public/                     # icon, manifest, service worker
```

`GET /api/health` trả trạng thái từng service phase 2 — nếu một service lỗi import,
route của nó không được đăng ký và `health` sẽ báo `false` thay vì im lặng 404.
Danh sách route đầy đủ: http://127.0.0.1:8765/docs

---

## Ghi chú vận hành

**Rate limit vnstock.** Free tier cho 20 request/phút. Khi vượt, thư viện gọi
`sys.exit()` và giết worker — `vnstock_safe.py` patch lại để lỗi propagate bình thường.
Các endpoint quét nhiều mã (heatmap ngành, quét an toàn) đã giới hạn số worker và cache
dài để nằm trong hạn mức; nới thêm sẽ gặp lỗi rate limit. `stock_service` cache dữ liệu
giá theo TTL (5 phút trong phiên, 30 phút ngoài phiên) vì biểu đồ, bộ lọc an toàn, cảnh
báo và bản tin đều xin cùng một bộ nến.

**Nguồn dữ liệu cơ bản.** Thứ tự thử là KBS → VCI. VCI trên free tier hiện chỉ trả số
liệu đến 2018, nên chỉ dùng làm dự phòng; khi phải rơi về nó, payload có `stale: true`
và UI hiện cảnh báo.

**Source hợp lệ của vnstock 4.0.4.** `Quote` nhận `kbs, vci, msn, dnse, ...`; `Company`,
`Trading` và `Finance` chỉ nhận `VCI` hoặc `KBS`. Truyền `TCBS` sẽ raise ngay lúc khởi
tạo — nhánh fallback dùng source đó là code chết, đừng thêm lại.

**Company.events() là endpoint gộp.** vnstock 4.0.4 KHÔNG có `insider_deals()` hay
`dividends()`. Mọi sự kiện doanh nghiệp nằm trong `events()`, phân biệt bằng cột
`category`: `MAJOR_SHAREHOLDER_TRADING` (giao dịch nội bộ), `DIVIDEND`,
`SHAREHOLDER_MEETING`. Chi tiết giao dịch nội bộ không có cột riêng — phải parse chuỗi
`event_title_vi` dạng `"Nguyễn Văn Khoa - Đăng kí Mua 428,368 FPT"`.

**Khối ngoại.** Lấy từ `Trading.price_board(symbols)` — nhận nhiều mã trong MỘT request
nên xếp hạng cả VN100 vẫn chỉ tốn 1 call. Giá trị trả về là VND nguyên, không phải tỷ.

**Heatmap ngành.** Ngành = ICB cấp 2 (`icb_level == 2`); gộp cả 4 cấp sẽ ra cả "Tài
chính" lẫn "Dịch vụ tài chính" đứng cạnh nhau. Mỗi ngành chỉ lấy vài mã ĐẠI DIỆN thuộc
VN100 — lấy mã đầu danh sách sẽ ra toàn penny theo bảng chữ cái và cho ra những con số
vô nghĩa như "Xây dựng -9%". % thay đổi cache theo TỪNG mã (30 phút): mỗi lượt dựng
heatmap thường có vài mã bị rate-limit, giữ lại phần lấy được để lượt sau lấp dần thay
vì vứt đi. Heatmap chỉ được cache khi đủ ít nhất một nửa số ngành.

**Giá ngoài giờ.** Hết phiên thì vnstock không còn dữ liệu khớp lệnh, backend trả giá
đóng cửa phiên gần nhất kèm `is_intraday: false` để UI ghi rõ "Đóng cửa <ngày>".

**Cảnh báo lưu ở DB, không phải file.** Production chạy `gunicorn --workers 2`:
mỗi worker có state in-memory riêng và filesystem của Railway/Render là ephemeral,
nên file JSON vừa mất đồng bộ giữa worker vừa bị xoá mỗi lần redeploy. Bảng `alert`
nằm cùng DB với sổ giao dịch thật. Điều kiện "AI đổi tín hiệu" đã bị gỡ cùng nhãn
MUA/BÁN của AI; rule cũ còn trong DB thì bị bỏ qua khi kiểm tra, không làm hỏng lượt.

**Cảnh báo tự kiểm tra ở client.** Không có worker chạy nền — panel Cảnh báo poll
`/api/alerts/check` mỗi 1 phút trong phiên (10 phút ngoài phiên) khi tab đang mở,
và bắn `Notification` nếu người dùng cho phép. Đóng tab thì không có gì chạy.

**Icon PWA.** `public/icon.svg` là bản gốc; PNG 192/512 và bản maskable sinh bằng
`frontend/scripts/generate_icons.py` (cần Pillow). Chrome yêu cầu ít nhất một PNG
>= 192px mới cho cài đặt, và icon maskable phải chừa safe zone 80%.

**Chia cột theo container, không theo viewport.** Panel "Toàn cảnh thị trường"
nằm trong rail ~300px ở desktop nhưng chiếm nguyên bề rộng trên mobile. Dùng
media query theo viewport thì rail bị xẻ đôi thành hai cột ~140px và mã CK cụt
chữ — các panel này dùng `container-type: inline-size` + `@container`.

**Thứ tự cột trên mobile.** DOM xếp rail trái → giữa → phải, nên khi dồn về một
cột người dùng phải cuộn qua ~3,6 màn hình panel phụ mới tới biểu đồ. Mobile đảo
thứ tự bằng `order` để biểu đồ + danh mục lên đầu.

**Biểu đồ dùng 3 chart instance.** lightweight-charts v4 chưa có pane nội bộ (đó
là v5), nên giá/RSI/MACD là ba chart riêng, đồng bộ `timeScale` và crosshair thủ
công. Thang giá bị ép `minimumWidth` cố định để trục thời gian ba khung thẳng
hàng — bỏ ràng buộc này là ba khung lệch nhau ngay.

**Mã chứng khoán VN được phép chứa CHỮ SỐ.** HT1 (Hà Tiên 1), NT2, PC1, TV2,
CC1, C4G... — 160 trên 1.881 mã 3 ký tự có chữ số, tức ~8,5% thị trường. Dùng
`symbol_utils.is_vn_symbol()`, KHÔNG viết lại `len(s)==3 and s.isalpha()`: cách
đó từng khiến các dòng HT1/PC1 trong sao kê bị bỏ im lặng lúc nhập, và
`/api/stocks/historical?symbol=HT1` trả 400.

**Không còn tính năng giả lập.** Danh mục ảo và backtest đã bị gỡ (tháng 9/2026).
Lý do: người dùng mục tiêu là nhà đầu tư mới, không phải trader. Một danh mục
tiền ảo 100 triệu và kết quả backtest quá khứ tạo cảm giác "đã kiểm chứng" trong
khi không dự báo được gì, làm loãng thứ thật sự quan trọng là danh mục thật.

**Sổ lệnh thật nằm ở bảng riêng.** `real_txn` tách khỏi `txn` (giả lập) vì hai
vòng đời khác nhau: danh mục giả lập reset thoải mái, còn sổ giao dịch thật mất
là không dựng lại được. `/api/real/reset` bắt buộc `confirm=true`.

**Chỉ báo cần dữ liệu mồi.** `fetch_stock_data` luôn tải thêm ~350 ngày trước khoảng
yêu cầu rồi mới cắt, nếu không EMA200 và RSI ở các nến đầu chỉ là số rác. Nến chưa đủ
dữ liệu mồi trả `null`, không phải số bịa.

---

## Deploy

**Frontend → Vercel, Backend → Railway/Render, Database → Neon.**
Chi tiết trong [DEPLOY.md](DEPLOY.md); `render.yaml` sẵn sàng nếu muốn Render thay Railway.

**Backend KHÔNG chạy được trên Vercel** — không phải vì lười cấu hình mà vì các
ràng buộc kỹ thuật dưới đây (riêng mục 2 và 3 đã đủ để loại Vercel):

1. *Sát giới hạn dung lượng.* Vercel Python function giới hạn 250 MB unzipped, và
   riêng pandas + numpy đã ~112 MB, chưa tính vnstock, yfinance, psycopg. Bản cũ còn
   dùng google-generativeai kéo theo grpc (~128 MB) nên vượt hẳn; sau khi chuyển
   sang google-genai (không dùng grpc) phần này nhẹ hơn nhiều, nên dung lượng một
   mình có thể không còn là lý do quyết định — chưa đo lại.
2. *Cache in-process biến mất.* App dựa nhiều vào TTLCache (chỉ số cơ bản 1 giờ,
   heatmap 30 phút, index 1.721 mã 24 giờ). Serverless không giữ được bộ nhớ
   giữa các lần gọi → mỗi request lạnh phải dựng lại index từ vnstock, mà
   vnstock chỉ cho 20 request/phút.
3. *Quá thời gian thực thi.* Heatmap ngành mất ~2 phút, quét an toàn nhiều mã còn
   lâu hơn. Vercel cắt ở 60 giây.

Railway/Render giữ tiến trình chạy liên tục nên không dính cả ba.

### Kiểm tra Neon trước khi deploy

Toàn bộ test tự động chạy trên SQLite (chúng chủ động xoá `DATABASE_URL`), nên
nhánh Postgres — kiểu boolean, `RETURNING`, connection pool — chưa được test tự
động. Chạy script này một lần sau khi tạo Neon database:

```bash
cd backend
DATABASE_URL="postgresql://...-pooler.../neondb?sslmode=require" ../.venv/Scripts/python.exe scripts/check_neon.py
```

Script chạy một vòng CRUD đầy đủ trên mọi bảng rồi dọn sạch dữ liệu test. Thoát
mã 0 nghĩa là an toàn để deploy.
