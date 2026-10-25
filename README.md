# Mạch Thị Trường

Vĩ mô · Vị thế · Tin tức cho GC, ES, NQ, CL — công cụ học và theo dõi. Công khai, miễn phí cho mọi người, chạy với chi phí 0 đồng.

| Mục | Nguồn (miễn phí, không cần API key) | Tần suất |
|---|---|---|
| Biểu đồ giá tham chiếu | Widget TradingView | Trực tiếp |
| Vị thế quỹ lớn (COT) | CFTC, báo cáo Legacy | Thứ Sáu hằng tuần |
| Tồn kho dầu Mỹ | EIA, Weekly Petroleum Status | Thứ Tư hằng tuần |
| Động lực vĩ mô | U.S. Treasury (lợi suất danh nghĩa, lợi suất thực), Fed New York (EFFR) | Hằng ngày |
| Kịch bản để quan sát | Tự suy ra từ COT, vĩ mô, EIA (mang tính giáo dục) | Mỗi lần cập nhật |
| Tin tức | RSS của Fed, EIA, CFTC và các trang tin tài chính | 30 phút |
| Lịch vĩ mô (giờ VN) | Forex Factory | 30 phút |
| Góc học orderflow | Nội dung tĩnh | — |

Tin tức chỉ hiện tiêu đề, tóm tắt ngắn và link về bài gốc, không chép nguyên bài.

## Cấu trúc

```
feeds.json                    Danh sách nguồn RSS (sửa ở đây để thêm/bớt nguồn)
scripts/common.py             Hàm dùng chung
scripts/fetch_news.py         Tin tức + lịch kinh tế  -> site/data/news.json, calendar.json
scripts/fetch_market.py       COT, EIA, vĩ mô, kịch bản -> site/data/market.json
site/index.html               Trang web (một file, không cần build)
.github/workflows/update.yml  Chạy 2 script mỗi 30 phút và đăng lên GitHub Pages
```

Các script chỉ dùng thư viện chuẩn Python, không cần cài gì thêm. Nguồn nào tạm lỗi thì giữ lại số liệu cũ, trang không bị trống.

## Chạy thử trên máy

```bash
py scripts/fetch_news.py
```

```bash
py scripts/fetch_market.py
```

```bash
py -m http.server 8765 --directory site
```

Rồi mở http://localhost:8765

## Đăng lên mạng miễn phí (GitHub Pages) bằng GitHub Desktop

1. GitHub Desktop: **File → Add local repository…**, chọn thư mục này. Khi app báo chưa phải repository, bấm **create a repository** rồi **Create repository**.
2. Bấm **Publish repository**, **bỏ tích** "Keep this code private" (repo phải công khai thì mới miễn phí), rồi **Publish**.
3. Trên github.com, mở repo: **Settings → Pages → Source: GitHub Actions**.
4. Tab **Actions** → workflow "Cập nhật dữ liệu" → **Run workflow**. Chờ dấu ✅ xanh.
5. Địa chỉ web hiện ở **Settings → Pages**.

Sau này sửa file trên máy thì vào GitHub Desktop, ghi chú thay đổi, bấm **Commit to main** rồi **Push origin**. Trang tự đăng lại.

GitHub tự tắt lịch chạy định kỳ nếu repo không có commit nào trong 60 ngày. Khi đó vào tab Actions bấm bật lại.

## Miễn trừ trách nhiệm

Nội dung chỉ nhằm mục đích giáo dục và cung cấp thông tin, không phải lời khuyên đầu tư. Giao dịch hợp đồng tương lai có rủi ro cao và có thể mất toàn bộ vốn.
