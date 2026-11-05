# ⚡ HƯỚNG DẪN SỬ DỤNG forge-agent — cho người mới bắt đầu (Windows-first)

> forge-agent là trợ lý lập trình AI **tự host trên máy bạn** (kiểu Claude Code / Codex),
> chạy bằng key OpenRouter của chính bạn (BYOK). Không có key vẫn chơi được ở **DEMO MODE**.

---

## 0. forge-agent có gì

- **Web + TUI + CLI**: dùng qua trình duyệt (khuyên dùng), giao diện terminal, hoặc dòng lệnh.
- **3 chế độ**: `agent` (tự làm việc hết), `plan` (đưa kế hoạch chờ duyệt), `direct` (chat nhanh, không dùng tool).
- **An toàn 3 mức**: GUARDED (chặn lệnh nguy hiểm) / ASK (hỏi trước khi chạy) / AUTO (YOLO).
- **Checkpoint & hoàn tác**: mỗi lượt agent là 1 bản chụp git — undo/fork thoải mái.
- **18 preset MCP** (Playwright, File System, Postgres, GitHub, Context7, Sequential Thinking, Stripe…) — chi tiết `MCP_CATALOG.md`.
- **Skills** (thư mục kỹ năng chuẩn Anthropic) + lệnh riêng + subagents + vòng lặp nền.
- **Audit**: mọi tool-call của agent được ghi log, token tự mask (tab 📘 Audit).

---

## 1. Yêu cầu máy

| Cần | Ghi chú |
|---|---|
| Windows 10/11 (hoặc macOS/Linux) | PowerShell có sẵn là đủ |
| **Python 3.10+** (khuyên 3.11+) | tải: https://www.python.org/downloads/ — lúc cài **NHỚ tick "Add python.exe to PATH"** |
| Node.js 18+ (tùy chọn) | chỉ cần cho MCP dạng npx (Playwright, Memory, Brave…) — https://nodejs.org |
| Git (tùy chọn nhưng nên có) | checkpoint đầy đủ + autocommit — https://git-scm.com |

## 2. Cài & chạy (đúng 2 bước)

**Bước 1.** Giải nén thư mục `forge-agent` (hoặc `git clone` repo) vào chỗ dễ nhớ, ví dụ `D:\forge-agent`.

**Bước 2.** **Double-click `run_forge.bat`.** Lần đầu nó sẽ:
1. tự tạo môi trường ảo `.venv`;
2. tự `pip install` dependencies (~1 phút);
3. chạy server và **tự mở trình duyệt** `http://localhost:8000`.

Xong! Những lần sau chỉ mất vài giây (bỏ qua setup).

- Muốn chạy tay trong PowerShell (để xem log rõ):
  ```powershell
  cd D:\forge-agent
  py -3 scripts\launch.py          # hoặc: python scripts\launch.py
  ```
- macOS/Linux: `./run_forge.sh`
- Kiểm tra môi trường mà không khởi động: `py -3 scripts\launch.py --check`
- Đổi cổng (8000 bị chiếm): PowerShell `$env:FORGE_PORT=8010` rồi chạy lại bat.

## 3. Thêm key OpenRouter (hoặc chơi demo trước)

1. Tạo tài khoản https://openrouter.ai → vào **Keys** → *Create Key* → copy `sk-or-v1-…`.
2. Trên web: bấm **⚙** góc trên → dán key vào ô *API key* → Save. (CLI: gõ `/key sk-or-v1-…`.)
3. Chọn model (mặc định thường dùng được): ô *Model*, ví dụ `anthropic/claude-sonnet-4.5`.
4. Bấm **🩺 Hệ thống** → xem mục key/model đều OK (hoặc CLI `/doctor`).
5. Chưa có key? **Demo mode** vẫn mô phỏng agent tạo/sửa file để bạn quen giao diện — chỉ chậm ở chỗ không gọi model thật.

Lưu ý BYOK: tiền API trả thẳng cho OpenRouter theo dùng; lỗi `402/429` = hết credit / quá tốc độ (agent tự fallback model rẻ — xem phần 9).

## 4. Làm quen màn hình web

- **Thanh chat dưới cùng**: gõ nhiệm vụ thường (tiếng Việt OK). Gõ `/` để hiện gợi ý lệnh; gõ `@` để chèn file.
- **Chọn chế độ** cạnh ô chat: `agent` / `plan` / `direct` (mục 5).
- **Cần phê duyệt lệnh shell?** Agent sẽ hỏi: *Allow once* (cho 1 lần) / *Allow always* (ghi nhớ vào allowlist) / *Deny* (từ chối). Chế độ ASK/GUARDED mặc định.
- **⚙ có 7 tab**: 📡 Kết nối (API/connector) · 🛡 An toàn (chế độ duyệt, allow/deny) · 🔌 MCP · 🔗 Dịch vụ (18 gói mẫu) · 🧩 Skills · 📘 Audit (bảng tool-call, lọc ✅/❌, xuất CSV) · 🩺 Hệ thống (doctor).
- Đa phiên: nút phiên mới trên thanh bên; đổi phiên không mất dữ liệu (lưu `data/sessions/`).

## 5. Ba chế độ — dùng khi nào

| Chế độ | Hành vi | Dùng cho |
|---|---|---|
| `agent` | Tự đọc/viết file, chạy lệnh, tới khi xong (có hỏi khi cần duyệt) | Việc thật: "tạo trang X", "sửa bug Y" |
| `plan` | Chỉ đưa kế hoạch từng bước, KHÔNG đụng file | Việc lớn, muốn duyệt trước |
| `direct` | Chat thuần, không tool | Hỏi đáp, giải thích code |

## 6. Việc thường ngày — ví dụ từng bước

1. **Tạo thứ gì đó**: gõ `tạo file fizzbuzz.py in 1..100, chạy thử luôn` → agent viết + chạy + báo kết quả.
2. **Cho agent ngữ cảnh**: `@src/app.py` chèn file vào câu hỏi; kéo-thả ảnh vào ô chat để nói về ảnh.
3. **Hoàn tác**: lượt xong thấy sai → `/undo` (hoặc nút undo) quay về bản chụp trước; `/fork` tẽn nhánh làm song song.
4. **Tìm web**: thêm `:online` cuối câu — agent tìm rồi tổng hợp (cần bật web search trong ⚙ → An toàn).
5. **Khởi tạo dự án**: `/init` — agent tự viết `AGENTS.md` mô tả dự án cho các phiên sau.
6. **Review code**: `/review` (xem diff + góp ý), `/diff` (xem thay đổi).
7. **Tự động commit** (mặc định TẮT): ⚙ → bật *auto commit* — agent tự git-commit có tin nhắn chuẩn Conventional Commits + chữ ký 🤖.
8. **Làm việc nền**: `/loop 30 kiểm tra test và sửa nếu đỏ` — lặp mỗi 30s cho tới khi bạn `/loop stop`.

## 7. Kỹ năng, lệnh riêng, subagents

- **Skills** (🧩): thư mục `.forge/skills/` — mỗi skill là 1 `SKILL.md` có frontmatter `name` + `description`. Agent tự dùng khi hợp việc. Bật/tắt trong tab 🧩 (nó sửa frontmatter, hiệu lực ngay). 13 skill mẫu có sẵn.
- **Lệnh riêng**: file `.forge/commands/<tên>.md` → gõ `/<tên>` trong chat là chạy prompt đó.
- **Subagents**: `/run <agent-alias> <việc>` — chạy agent phụ (có thể dùng model rẻ), isolation `shared` hoặc `worktree` (nhánh git riêng, merge khi xong).
- **Sub-agent nền** (v0.32): ở Agent mode, yêu cầu “dùng `spawn_background_agent` để kiểm tra …” — bạn tiếp tục chat trong lúc agent phụ làm. Khi xong, kết quả tự vào `/inbox`; tối đa 3 tác vụ đang chạy/phiên và danh sách nền được xoá khi restart server.
- **Repo map**: `/repomap` để xem bản đồ file + hàm/lớp chính; `/repomap 10000` nếu muốn bản dài hơn. Workspace nhỏ được tự nạp map để agent định hướng nhanh hơn.

## 8. Kết nối thế giới ngoài (MCP + connectors)

18 gói mẫu — bấm ⚙ → 🔗 Dịch vụ, hoặc CLI `/connectors add <tên>`. Xem tool đã lên: `/mcp` (làm mới: `/mcp refresh`).

| Muốn… | Làm gì (PowerShell) |
|---|---|
| Tìm web (Brave, free 2k lượt/tháng) | `$env:BRAVE_API_KEY="BSA…"` → `/connectors add brave-search` |
| Agent lái trình duyệt | `/connectors add playwright` (cần Node) |
| Trí nhớ dài hạn | `/connectors add memory` (không cần gì) |
| Query database chỉ-đọc | `$env:DATABASE_URL="postgresql://user:pass@host:5432/db"` → `/connectors add postgres` |
| GitHub | `/connectors add github` → `/connectors auth github <PAT>` |
| Đọc tài liệu thư viện | `/connectors add context7` |
| Notion / Sentry / Linear (OAuth) | `/connectors add notion` → `/connectors oauth notion <client_id> <client_secret>` |
| Gmail, Drive, Sheets… (500+ app) | preset hub Composio — dán URL hub của bạn |

Mỗi tool MCP lần đầu chạy đều **hỏi duyệt** (allowlist) — không tool nào chạy lặng lẽ. Chi tiết 18 gói + bảo mật: `MCP_CATALOG.md`.

## 9. An toàn

- **Chế độ duyệt** (⚙ → 🛡): `GUARDED` (mặc định — chặn `rm -rf`, format…), `ASK` (hỏi mọi lệnh warn/danger), `AUTO` (không hỏi — **chỉ dùng trong máy ảo/Docker**).
- Cho phép/chặn lệnh theo glob: `allow_commands` / `deny_commands` trong ⚡ An toàn.
- **Docker sandbox** (tùy chọn): bật trong ⚙ → mọi lệnh shell chạy trong container.
- **Audit** 📘: mỗi tool-call 1 dòng (thời gian, phiên, tool, ms, args), token/key tự mask, xuất CSV được.
- Key lưu tại `data/secrets.json` (máy bạn, không gửi đi đâu khác); listing luôn hiện bản mask.

## 10. Sự cố thường gặp

| Hiện tượng | Xử lý |
|---|---|
| Cửa sổ bat nháy rồi tắt | Chạy trong PowerShell: `py -3 scripts\launch.py` — đọc lỗi thật |
| "Python not found" | Cài lại Python, **tick "Add python.exe to PATH"**, mở PowerShell mới thử lại |
| Chữ lỗi font trong terminal | `chcp 65001` trước khi chạy |
| Cổng 8000 bận | `$env:FORGE_PORT=8010` rồi chạy lại bat (hoặc tắt tiến trình cũ) |
| Lỗi 402/429 từ model | Hết credit / quá tốc độ OpenRouter — nạp tiền hoặc đổi model (`/model`); agent có fallback tự động |
| MCP server báo `error` | `/mcp` đọc dòng error — thường là thiếu biến môi trường (đặt lại rồi `/mcp refresh`) |
| OAuth mở trang không xong | Chạy lại `/connectors oauth …`; công ty chặn popup thì dán URL vào tab mới |
| `.venv` hỏng / cài lỗi | Xoá thư mục `.venv` → chạy lại `run_forge.bat` |
| Muốn reset sạch | Xoá `data/` (mất phiên) — skill nằm ở `~/.forge` nên không mất |

## 11. Cập nhật & gỡ

- **Cập nhật**: `git pull` (hoặc giải nén bản mới đè lên) → chạy lại `run_forge.bat` (tự cài deps mới nếu có).
- **Gỡ**: xoá thư mục forge-agent + xoá `~/.forge` (skill toàn cục) nếu muốn sạch tuyệt đối. Không có gì cài ngầm vào hệ thống.

## Phụ lục — Lệnh slash hay dùng

`/help` · `/new` · `/sessions` · `/use <sid>` · `/model <tên>` · `/key <key>` · `/mode <agent|plan|direct>` · `/undo` · `/fork` · `/init` · `/review` · `/diff` · `/repomap [budget]` · `/doctor` · `/audit [n]` · `/export` · `/mcp [refresh]` · `/connectors add|auth|remove|oauth` · `/loop <giây> <việc>` · `/loop stop` · `/run <alias> <việc>` · `/msg <sid> <nội dung>` · `/inbox` · `/memory`
