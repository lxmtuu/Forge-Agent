---
name: commit-vn
description: Viết commit message tiếng Việt theo Conventional Commits (feat/fix/...) từ diff thật của repo. Dùng khi người dùng yêu cầu commit, viết commit message, hoặc gói các thay đổi thành commit.
license: MIT
compatibility: Cần git trong PATH; chạy được trong mọi repo git của forge-agent.
metadata:
  ngôn-ngữ: vi
  tác-giả: forge-agent mẫu
---

# commit-vn — commit message tiếng Việt chuẩn Conventional Commits

## Các bước

1. Chạy `git status --short` và `git diff` (file đã theo dõi) / `git diff --cached`
   (file đã stage) để xem thay đổi thật. Không viết commit dựa trên đoán.
2. Nhóm thay đổi theo **mục đích** (một commit = một ý). Nếu repo có lịch sử commit,
   chạy `git log --oneline -10` để theo đúng văn phong cũ.
3. Viết tiêu đề theo format:

   ```
   <type>: <mô tả ngắn, không viết hoa đầu câu, không dấu chấm cuối>
   ```

   `type` ∈ `feat | fix | refactor | docs | test | chore | perf | style`.
   Tiêu đề ≤ 72 ký tự, tiếng Việt tự nhiên (vd: `fix: xử lý NULL khi đọc config`).
4. Thân commit (tùy chọn, khi diff phức tạp): giải thích **vì sao**, không liệt kê
   máy móc "thêm file x, sửa file y" — diff đã nói điều đó. Mỗi ý một dòng, ngắt dòng ~72 ký tự.
5. Đề xuất câu lệnh commit hoàn chỉnh cho người dùng chạy:

   ```bash
   git add <files>
   git commit -m "<tiêu đề>" -m "<thân (nếu có)>"
   ```

   Không tự chạy `git commit` khi chưa được người dùng đồng ý.

## Gotchas

- Đừng dùng type sai: sửa bug = `fix`, tính năng mới = `feat` — dù diff nhỏ.
- File sinh tự động (`node_modules`, `dist`, `__pycache__`) không được đưa vào commit.
- Nếu `git diff` trống nhưng có file untracked — hỏi người dùng có muốn đưa vào không,
  đừng tự ý `git add .`.

## Tài nguyên

- Chi tiết từng type + ví dụ hay/xấu: đọc `references/convention.md` trong thư mục skill này.
