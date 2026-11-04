# 🖥️ BUILD DESKTOP — đóng gói Forge thành phần mềm máy tính

Forge có 3 hình thái "phần mềm", giống hệt Claude Code / Codex / OpenCode:

| Hình thái | Lệnh | Giống với |
|---|---|---|
| **TUI** (mặc định) | `forge` | OpenCode / Claude Code — giao diện terminal toàn màn hình |
| **Web** | `forge --web` | Claude Code trên web — mở http://localhost:8000 |
| **EXE độc lập** | `forge.exe` | Phần mềm .exe chạy không cần cài Python |

## Cách 1 — Cài như package Python (khuyên dùng)

```bash
cd forge-agent
pip install -e .
```

Xong có lệnh `forge` trong PATH:
```bash
forge                          # TUI toàn màn hình
forge --web                    # web UI tại :8000
forge --once "viết fizzbuzz"   # chạy 1 lượt
forge --parallel "task A" "task B"
forge --list-sessions
```

## Cách 2 — Tự build .exe (PyInstaller)

Trên máy bạn (Windows/macOS/Linux đều được):
```bash
pip install . pyinstaller
cd web && npm ci && npm run build && cd ..   # để exe có sẵn web UI
pyinstaller forge.spec --noconfirm
# → dist/forge.exe  (Windows) hoặc dist/forge (Linux/macOS)
```

File exe chạy độc lập — người nhận không cần cài Python. Lưu ý: antivirus
đôi khi cảnh báo exe PyInstaller chưa ký số — chỉ là false positive phổ biến.

## Cách 3 — Để GitHub tự build (tự động cả 3 OS)

1. Push repo lên GitHub
2. Tạo release: `git tag v0.5.0 && git push origin v0.5.0`
3. Action `.github/workflows/release.yml` tự build **forge-windows.exe,
   forge-linux, forge-macos** và đính kèm vào release — tải về dùng ngay.

## Kiến trúc 3 tầng — 1 engine

```
                    ┌────────────────────────┐
   OpenRouter API   │      forge engine      │
◄──────────────────►│  agent loop + tools    │
                    │  sessions + workspace  │
                    └───────────┬────────────┘
        ┌───────────────────────┼──────────────────────┐
        ▼                       ▼                      ▼
  tui/app.py (Textual)   server/main.py (FastAPI)  cli/main.py (Rich REPL)
  = `forge`              = `forge --web`           = `forge --repl`
  opencode-style         Claude-Code-web style     Codex-CLI style
```

## Lưu ý TUI

- Phím tắt: `Ctrl+Q` thoát · `Ctrl+N` phiên mới · `Ctrl+R` refresh file tree
- Lệnh trong ô nhập: `/help` `/key` `/model` `/mode` `/usage` `/files` `/quit`
- Phê duyệt lệnh (ask mode) hiện dạng **popup modal** trong terminal
- Windows Terminal / PowerShell 7 hiển thị đẹp nhất; CMD cũ có thể thiếu màu
