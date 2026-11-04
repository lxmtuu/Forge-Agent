# 📋 AUDIT — repo `cporter202/API-mega-list`

> Ngày audit: 2026-11-04 · Bản audit đầy đủ của thư mục `open-source-apis-84` và toàn repo.

## 1. Thông tin định danh

| Mục | Giá trị |
|---|---|
| Repo | github.com/cporter202/API-mega-list |
| Stars / Forks | 8.290 ⭐ / 1.616 forks (tại thời điểm audit) |
| Tạo | 2025-12-09 · Commit cuối: 2026-10-20 |
| License | **Không có** (all rights reserved) |
| Tác giả | cporter202 — sở hữu 41+ repos cùng mô hình "API list + affiliate link" |

## 2. Bản chất

Repo **không phải danh sách API open-source** mà là **catalog Apify Actors sinh tự động**:

- Script `settings/fetch_apify_actors.js` pull toàn bộ Apify Store qua `api.apify.com/v2/store`
  rồi gắn mã tiếp thị liên kết **cứng trong code**: `AFFILIATE_PARAM = '?fpr=p2hrc6'`.
- **71.599/71.602 link** trong repo mang mã affiliate đó.
- `SPONSORED_PARTNERS.md` xác nhận có **bán vị trí tài trợ** (paid placement).

## 3. Kiểm chứng số liệu

| Tuyên bố | Thực tế đo được |
|---|---|
| "11.860 core directory APIs" | 30.285 dòng bảng / 24 mục, chỉ có **11.661 actor duy nhất** — cùng actor lặp tới 6 mục |
| "APIs" | Là **Apify Actors** (app cloud có phí trên nền tảng Apify), không phải API truyền thống |
| "Updated Daily" | Commit cuối 2026-10-20 (2 tuần trước ngày audit) |
| Thư mục `open-source-apis-84` | 84 dòng = dump theo tag "Open source" của Apify Store; **lẫn actor đóng/tính phí** (Costco Scraper, Ashby Job Scraper…) |

## 4. Đánh giá rủi ro

| Hạng mục | Đánh giá |
|---|---|
| Mã độc | ✅ **Không** — chỉ Markdown tĩnh + script Node lành tính (fetch API, generate README) |
| Lừa đảo | ⚠️ **Nửa vời** — minh bạch về sponsor nhưng tên gọi "open-source APIs" gây hiểu lầm; mọi link kiếm hoa hồng cho tác giả |
| Chất lượng nội dung | ❌ Mô tả cắt 150 ký tự, không có giá/rating/số user, trùng lặp hàng loạt, không license |
| Giá trị sử dụng | ⚠️ Dùng OK như **mục lục khám phá Apify Store** — nhưng phải kiểm tra từng actor riêng (giá, model billing, server ngoài) |

## 5. Kết luận

1. Repo **an toàn để đọc**, không an toàn để **tin mù quáng**: số liệu phình to, label sai, mục tiêu chính là affiliate.
2. Khi dùng bất kỳ actor nào từ đó: xem trang pricing riêng, kiểm tra biến môi trường `WORKER_BASE_URL`
   (dấu hiệu dữ liệu đi qua server của developer bên thứ ba), thử với credit miễn phí trước.
3. Bài học thiết kế cho dự án Forge: **không phụ thuộc actor đóng** cho lõi agent — tự xây engine
   (chính là thư mục `engine/` của repo này), chỉ dùng dịch vụ ngoài ở lớp tích hợp tuỳ chọn.

## 6. Phụ lục — các actor đáng chú ý trong `open-source-apis-84` liên quan tới việc xây agent

| Actor | Vai trò tham khảo cho Forge |
|---|---|
| `apify/ai-code-sandbox` | Mô hình sandbox chạy code cho agent (web shell + REST + MCP, Python/Node) — đúng kiến trúc roadmap Docker sandbox |
| `apify/ai-web-agent` | Prompt điều khiển browser — tham khảo cho tool browser sau này |
| `jiri.spilka/dataset-query-engine` | NL → SQL → tổng hợp — tham khảo cho tool query dữ liệu |
| `apify/cheerio-scraper`, `beautifulsoup-scraper` | Mã nguồn mở thật của Apify — tham khảo code |
| Nhóm `mcp-servers-apis-289` (repo gốc) | Hệ sinh thái MCP server — nối vào roadmap MCP client của Forge |
