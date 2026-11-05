# Conventional Commits — chi tiết các type (tiếng Việt)

| Type | Dùng khi | Ví dụ tiêu đề |
|---|---|---|
| `feat` | Thêm tính năng mới cho người dùng | `feat: thêm hàng đợi tin nhắn khi agent đang chạy` |
| `fix` | Sửa lỗi hành vi sai | `fix: kill_background báo sai trạng thái do race` |
| `perf` | Cải thiện hiệu năng không đổi hành vi | `perf: cache giá model 1 giờ thay vì gọi mỗi lượt` |
| `refactor` | Cấu trúc lại code, không đổi hành vi | `refactor: tách skillmgr khỏi skills.py` |
| `docs` | Chỉ thay đổi tài liệu | `docs: hướng dẫn cài skill từ skills.sh` |
| `test` | Thêm/sửa test | `test: smoke v0.15 cho skills chuẩn SKILL.md` |
| `chore` | Build, phụ thuộc, tooling | `chore: thêm pyyaml vào requirements` |
| `style` | Định dạng, dấu cách, không đổi logic | `style: đồng bộ thụt lề 4 dấu cách` |

## Tiêu đề hay vs thiếu

- ✅ `fix: chặn SSRF trong fetch_url kể cả redirect nội bộ` — nói đúng việc làm.
- ❌ `update code` — không nói làm gì; ❌ `Fix Bug!!!` — viết hoa + cảm thán.
- ✅ Dùng chữ "khi/để" để nói bối cảnh trong thân commit: "Để tránh race khi pump
  chưa kịp chạy, kill tự cập nhật trạng thái ngay sau wait()".

## Scope (tùy chọn)

`<type>(<scope>): ...` khi cần chỉ vùng ảnh hưởng — vd `feat(web): thanh tiến độ todo`,
`fix(engine): guard chặn rm -rf`. Scope bằng tiếng Việt không dấu, ngắn.
