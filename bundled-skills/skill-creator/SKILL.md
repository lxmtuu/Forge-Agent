---
name: skill-creator
description: Tạo skill mới đúng chuẩn Agent Skills (SKILL.md). Dùng khi người dùng muốn tạo skill, đóng gói quy trình thành skill, hoặc hỏi cách viết SKILL.md.
license: MIT
compatibility: forge-agent v0.16+ (có /skills new, /skills trust)
metadata:
  tác-giả: forge-agent
  nguồn: bundled
---

# skill-creator — tự tạo skill mới đúng chuẩn Agent Skills

## Quy trình

1. Làm rõ với người dùng 2 điều (chính 2 câu này thành `description` trong frontmatter):
   - Skill này **LÀM GÌ**?
   - **KHI NÀO** model nên dùng? (description là "trigger" — phải nói cả hai)
2. Đặt tên **kebab-case** `[a-z0-9-]`, ≤64 ký tự, trùng tên thư mục
   (vd: `review-api`, `deploy-staging` — không chữ hoa, không dấu tiếng Việt).
3. Scaffold có sẵn: chạy `/skills new <tên> <mô tả>` → tạo
   `<workspace>/.forge/skills/<tên>/SKILL.md` đúng mẫu. Có thể tự viết file theo mẫu dưới.
4. Viết body **< 5.000 tokens**:
   - Các bước đánh số, mỗi bước một hành động cụ thể.
   - **Cung cấp mặc định, đừng đưa menu lựa chọn** ("dùng X" thay vì "có thể dùng X hoặc Y hoặc Z").
   - Mục **Gotchas**: bẫy thường gặp, điều KHÔNG nên làm.
5. Cần tài nguyên đi kèm? Tạo trong cùng thư mục skill:
   - `scripts/` — script chạy được (KHÔNG tương tác, có `--help`); agent chạy qua tool shell
     với đường dẫn tuyệt đối (thư mục gốc được ghi trong catalog).
   - `references/` — tài liệu tham khảo, chỉ đọc khi cần.
   - `assets/` — template/file tĩnh.
6. Kiểm tra: chạy `/skills` — skill phải hiện **không có ⚠**; mô tả rõ ràng; thử gọi `/<tên>`.
7. Nhắc người dùng: skill nằm trong dự án nên lần đầu model dùng sẽ cần
   `/skills trust <tên>` (chống prompt injection từ repo lạ — an toàn là trên hết).

## Mẫu frontmatter

```
---
name: <tên-kebab-case>
description: <Làm gì. Dùng khi…>
license: MIT
---
```

## Gotchas

- Đừng nhồi điều kiện kích hoạt vào body — **description mới là chỗ model nhìn** để quyết định đọc.
- Body dài quá 5k tokens → tách phần tham khảo sang `references/`.
- Tên thư mục phải trùng đúng `name` trong frontmatter, nếu lệch chỉ là cảnh báo nhưng nên sửa.
- Skill chỉ nên chứa **tri thức ổn định** (quy trình, chuẩn) — không chứa dữ liệu đổi theo lần gọi.
