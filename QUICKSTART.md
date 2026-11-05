# ⚡ QUICKSTART — chạy Forge Agent lần đầu (5 phút)

> 🪟 **Windows**: mọi lỗi encode (`charmap codec`, ký tự tiếng Việt) đã được vá từ v0.3.1. Nếu lệnh `python` không có sẵn, thử `py -3` thay thế.

## ⚡ CÁNH NHANH NHẤT: Windows double-click `run_forge.bat`
Tự tạo .venv → cài dependencies → chạy server → mở trình duyệt. macOS/Linux: `./run_forge.sh`. Bản local chỉ listen `127.0.0.1`. Hướng dẫn đầy đủ: **USER_GUIDE.md**.

## 0. Muốn có “phần mềm” như Claude Code/OpenCode?
```bash
pip install -e .
forge        # TUI toàn màn hình trong terminal
```
Chi tiết: **BUILD_DESKTOP.md** (gồm cách build file .exe độc lập).

## 1. Cài Python dependencies (không cần Node — Web đã build sẵn)
```bash
pip install -r requirements.txt
```

## 2. Chạy local
```bash
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
```
Mở **http://localhost:8000**.

## 3. Dùng ngay (Demo mode — không cần key)
Agent vẫn chạy tool THẬT (tạo file, chạy lệnh) nhưng “não” là kịch bản mẫu. Bấm thử **⚡ Song song**, hoặc cấu hình provider để dùng model thật.

## 4. Kích hoạt model thật — OpenRouter hoặc Google Gemini

### Cách khuyến nghị: terminal setup, key nhập ẩn
```bash
# OpenRouter — tạo key tại https://openrouter.ai/keys
python scripts/setup_keys.py --provider openrouter

# Hoặc Google Gemini — tạo key tại https://aistudio.google.com/api-keys
python scripts/setup_keys.py --provider google

python scripts/setup_keys.py --check
```

Key nằm ở `data/provider-secrets.json` (không trong `config.json`, git hay ZIP). Ở bản local, bạn vẫn có thể nhập key qua **⚙ Cài đặt** hoặc CLI `/key`; không dùng cách đó trên shared release.

Model mặc định: OpenRouter `anthropic/claude-sonnet-5.5`; Google `gemini-3.8-flash`. Gửi thử: *“Viết game rắn bằng HTML/JS vào 1 file rồi chạy test”*.

## 5. Một server dùng chung (release mode)

```bash
python scripts/setup_keys.py --provider openrouter --release
# hoặc --provider google
python scripts/launch.py --release --no-browser
```

- Đăng nhập username **`forge`** bằng release password vừa tạo.
- Settings/key input trên Web bị khóa; chỉ operator đổi qua terminal.
- Bắt buộc HTTPS reverse proxy khi truy cập qua mạng. Đọc **SECURITY.md + DEPLOY.md** trước khi public.
- Nếu cần listen mọi interface: đặt `FORGE_HOST=0.0.0.0` **chỉ sau khi** release auth và proxy đã sẵn sàng.

## 6. CLI (tùy chọn)
```bash
python cli/main.py
python cli/main.py --once "viết fizzbuzz rồi chạy"
python cli/main.py --parallel "task A" "task B"
```

## An toàn
- Mặc định **Guarded**: lệnh nguy hiểm bị chặn. Có thể đổi **ASK** hoặc **AUTO** (AUTO chỉ nên dùng trong sandbox).
- Shell/hook/git/MCP không tự thừa kế provider key; MCP chỉ nhận secret được khai báo explicit.
- Release có authentication, CORS same-origin và rate-limit; vẫn chỉ nên cấp cho nhóm tin cậy, không phải multi-tenant isolation.

Chi tiết: **README.md · USER_GUIDE.md · SECURITY.md · DEPLOY.md**.
