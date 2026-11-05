# ⚡ QUICKSTART — chạy Forge Agent lần đầu (5 phút)

> 🪟 **Windows**: mọi lỗi encode (`charmap codec`, ký tự tiếng Việt) đã được vá từ v0.3.1. Nếu lệnh `python` không có sẵn, thử `py -3` thay thế.

## ⚡ CÁNH NHANH NHẤT: Windows double-click `run_forge.bat`
Tự tạo .venv → cài dependencies → hỏi tạo admin nếu chưa có user → chạy server → mở trình duyệt. macOS/Linux: `./run_forge.sh`. Bản local chỉ listen `127.0.0.1`. Hướng dẫn đầy đủ: **USER_GUIDE.md**.

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

## 2. Tạo admin và chạy local
```bash
# Lần đầu: hỏi email, password nhập ẩn ≥16 ký tự.
python scripts/setup_auth.py
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
```
Mở **http://localhost:8000** và đăng nhập bằng account vừa tạo. Nếu chạy bằng `run_forge.bat`/`run_forge.sh`, launcher tự hỏi bước tạo admin này.

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

Từ v0.36, lưu lần lượt OpenRouter/Google/Custom để dùng **một key cho mỗi provider cùng lúc**. Settings có bảng trạng thái từng provider; ô password trống sau khi mở lại là hành vi bảo mật, hãy nhìn trạng thái **đã lưu** thay vì nhập lại. Model ở thanh trên được lưu theo session ngay khi **Enter hoặc rồi ô**, không cần gửi prompt.

Model mặc định: OpenRouter `anthropic/claude-sonnet-5.5`; Google `gemini-3.8-flash`. Gửi thử: *“Viết game rắn bằng HTML/JS vào 1 file rồi chạy test”*.

## 5. Một server dùng chung (release mode)

```bash
python scripts/setup_keys.py --provider openrouter --release
# hoặc --provider google
python scripts/launch.py --release --no-browser
```

- Nếu chưa có user, setup yêu cầu tạo **email + password admin đầu tiên** (password nhập ẩn, ≥16 ký tự). Có thể tạo thêm bằng `python scripts/setup_auth.py --email member@example.com`.
- Đăng nhập bằng tài khoản email/password riêng hoặc Google OIDC đã cấu hình; **không còn username chung `forge`**. Admin tạo user trong ⚙ → Team; public signup mặc định tắt, khi được bật sẽ có form **Đăng ký** và chỉ tạo member.
- Mỗi user chỉ thấy session/workspace của mình; member chọn model theo session nhưng không đổi default/settings toàn server.
- Settings/key input toàn server bị khóa ở release; chỉ operator đổi qua terminal.
- Bắt buộc HTTPS reverse proxy khi truy cập qua mạng. Đặt `FORGE_PUBLIC_URL=https://...` hoặc `FORGE_COOKIE_SECURE=1`. Đọc **SECURITY.md + DEPLOY.md** trước khi public.
- Nếu cần listen mọi interface: đặt `FORGE_HOST=0.0.0.0` **chỉ sau khi** user auth và proxy đã sẵn sàng.

## 6. CLI (tùy chọn)
```bash
python cli/main.py
python cli/main.py --once "viết fizzbuzz rồi chạy"
python cli/main.py --parallel "task A" "task B"
```

## An toàn
- Mặc định **Guarded**: lệnh nguy hiểm bị chặn. Có thể đổi **ASK** hoặc **AUTO** (AUTO chỉ nên dùng trong sandbox).
- Shell/hook/git/MCP không tự thừa kế provider key; MCP chỉ nhận secret được khai báo explicit.
- Release có per-user cookie auth + owner ACL, CSRF, CORS same-origin và rate-limit; đây không phải OS sandbox. Chỉ bật public signup khi operator chấp nhận cấp workspace cho người ngoài và đã có kiểm soát abuse phù hợp.

Chi tiết: **README.md · USER_GUIDE.md · SECURITY.md · DEPLOY.md**.
