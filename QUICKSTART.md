# ⚡ QUICKSTART — chạy Forge Agent lần đầu (5 phút)

> 🪟 **Windows**: mọi lỗi encode (`charmap codec`, ký tự tiếng Việt) đã được vá từ
> v0.3.1 — bạn chỉ cần dùng bản zip này trở đi. Nếu lệnh `python` không có sẵn,
> thử `py -m uvicorn ...` thay thế.

## 0. Muốn có "phần mềm" như Claude Code/OpenCode?
```bash
pip install -e .
forge        # ← TUI toàn màn hình trong terminal!
```
Chi tiết: **BUILD_DESKTOP.md** (gồm cả cách build file .exe độc lập).

## 1. Cài Python dependencies (không cần Node — web đã build sẵn)
```bash
pip install -r requirements.txt
```

## 2. Chạy
```bash
python -m uvicorn server.main:app --host 0.0.0.0 --port 8000
```
Mở trình duyệt: **http://localhost:8000**

## 3. Dùng ngay (Demo mode — không cần key)
Ở chế độ Demo, agent vẫn chạy tool THẬT (tạo file, chạy lệnh) nhưng "não"
là kịch bản mẫu. Bấm thử nút **⚡ Song song**, hoặc nạp key để dùng thật:

## 4. Kích hoạt não thật — OpenRouter (khuyên dùng)
1. Tạo key miễn phí: https://openrouter.ai/keys
2. Trong web: **⚙ Cài đặt** → dán key → Lưu (hoặc CLI: `/key sk-or-...`)
3. Gửi nhiệm vụ, ví dụ: *"Viết game rắn bằng HTML/JS vào 1 file rồi chạy test"*

Model mặc định: `anthropic/claude-sonnet-5.5` — đổi model bất kỳ trong ⚙
(453 model tự đồng bộ, kèm giá $/M tokens — hover vào chip để xem).

## 5. CLI (tuỳ chọn)
```bash
python cli/main.py                       # REPL kiểu Codex
python cli/main.py --once "viết fizzbuzz rồi chạy"
python cli/main.py --parallel "task A" "task B"   # sub-agent song song
```

## An toàn
- Mặc định **Guarded**: lệnh nguy hiểm bị chặn. Đổi thành **🔔 Hỏi từng lệnh**
  hoặc **⚡ Auto** trong ⚙ Cài đặt (hoặc CLI `/mode ask|auto`).
- Server chạy local thì thoải mái; nếu public → đọc **DEPLOY.md** (bắt buộc auth).

Chi tiết đầy đủ: README.md · Kiến trúc/bảo mật: README.md + DEPLOY.md
