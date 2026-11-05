# ⚡ HƯỚNG DẪN SỬ DỤNG forge-agent — cho người mới bắt đầu (Windows-first)

> forge-agent là trợ lý lập trình AI **tự host trên máy bạn** (kiểu Claude Code / Codex),
> chạy bằng OpenRouter/Google Gemini của chính bạn (BYOK) hoặc key do operator cấp cho shared server. Không có key vẫn chơi được ở **DEMO MODE**.

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
3. nếu chưa có user, hỏi **email + password admin** (password nhập ẩn, ≥16 ký tự);
4. chạy server và **tự mở trình duyệt** `http://localhost:8000` để đăng nhập.

Xong! Những lần sau chỉ mất vài giây (bỏ qua setup). Có thể tạo trước bằng `py -3 scripts\setup_auth.py` nếu muốn.

- Muốn chạy tay trong PowerShell (để xem log rõ):
  ```powershell
  cd D:\forge-agent
  py -3 scripts\launch.py          # hoặc: python scripts\launch.py
  ```
- macOS/Linux: `./run_forge.sh`
- Kiểm tra môi trường mà không khởi động: `py -3 scripts\launch.py --check`
- Đổi cổng (8000 bị chiếm): PowerShell `$env:FORGE_PORT=8010` rồi chạy lại bat.

## 3. Thêm OpenRouter / Google Gemini (hoặc chơi demo trước)

**Cách khuyến nghị — terminal, key nhập ẩn:**
1. Tạo key tại https://openrouter.ai/keys hoặc https://aistudio.google.com/api-keys.
2. Chạy `python scripts/setup_keys.py --provider openrouter` (Windows: `py -3 scripts\setup_keys.py --provider openrouter`). Với Google, đổi thành `--provider google`.
3. Nhập key vào prompt ẩn, chọn model. Kiểm tra bằng `python scripts/setup_keys.py --check` — chỉ thấy bản mask.
4. Khởi động lại Forge, bấm **🩺 Hệ thống** (hoặc CLI `/doctor`) để xem provider/key/model.

Trên **máy cá nhân**, bạn vẫn có thể bấm **⚙** → dán key → Save, hoặc CLI `/key`. Shared release sẽ khóa cách nhập qua Web. Chưa có key? **DEMO MODE** vẫn mô phỏng agent tạo/sửa file để làm quen.

Lưu ý chi phí: BYOK trả trực tiếp cho provider; `402/429` thường là hết credit/quá tốc độ. Google Free Tier có thể dùng dữ liệu cải thiện sản phẩm — không gửi code bí mật lên Free Tier.

## 4. Làm quen màn hình web

- **Thanh chat dưới cùng**: gõ nhiệm vụ thường (tiếng Việt OK). Gõ `/` để hiện gợi ý lệnh; gõ `@` để chèn file.
- **Top bar**: xem tên/ID phiên, mở **Workspace** hoặc Settings. Dưới 1100px Workspace là drawer; sidebar và Workspace đều đóng bằng nút ✕, chạm vùng nền hoặc Escape.
- **Chọn chế độ** trong toolbar ô chat: `agent` / `plan` / `direct` / `architect` / `battle`; nút **Song song** và Model của phiên nằm cùng toolbar.
- **Cần phê duyệt lệnh shell?** Agent sẽ hỏi: *Allow once* (cho 1 lần) / *Allow always* (ghi nhớ vào allowlist) / *Deny* (từ chối). Chế độ ASK/GUARDED mặc định.
- **⚙ Settings**: navigation bên trái (hoặc thanh ngang trên mobile), nội dung cuộn riêng và nút Save luôn ở footer. Admin có 9 nhóm: Kết nối · Giao diện · Team · An toàn · MCP · Dịch vụ · Skills · Audit · Hệ thống. Member thấy đúng ba nhóm usable: **Giao diện · Skills · Audit**; model theo phiên vẫn chọn ở composer.
- Đa phiên: nút phiên mới trên thanh bên; đổi phiên không mất dữ liệu (lưu `data/sessions/`).

### Đổi ngôn ngữ / Language

- **Tiếng Việt:** Forge vẫn mặc định tiếng Việt. Vào **⚙ Cài đặt → 🎨 Giao diện → Ngôn ngữ giao diện** để chọn **English**, hoặc bấm **EN** ngay trên màn hình đăng nhập. Lựa chọn được lưu trên thiết bị/trình duyệt và giữ nguyên sau khi reload.
- **English:** choose **EN** on the login screen, or open **⚙ Settings → 🎨 Appearance → Interface language** and select **English**. To return to Vietnamese, select **Tiếng Việt**. This preference is local to the current browser/device.
- Ngôn ngữ này đổi labels, nút, placeholders, thông báo hệ thống và kịch bản **Demo**. Forge không tự dịch câu trả lời của model thật; ngôn ngữ phản hồi của provider vẫn phụ thuộc prompt và model.

## 5. Năm chế độ — dùng khi nào

| Chế độ | Hành vi | Dùng cho |
|---|---|---|
| `agent` | Tự đọc/viết file, chạy lệnh, tới khi xong (có hỏi khi cần duyệt) | Việc thật: "tạo trang X", "sửa bug Y" |
| `plan` | Chỉ đưa kế hoạch từng bước, KHÔNG đụng file | Việc lớn, muốn duyệt trước |
| `direct` | Chat thuần, không tool | Hỏi đáp, giải thích code |
| `architect` | Model mạnh lập kế hoạch rồi model thực thi triển khai | Thay đổi cần tách thiết kế/thi công |
| `battle` | Chạy cùng prompt trên nhiều model | So sánh và chọn kết quả phù hợp |

## 6. Việc thường ngày — ví dụ từng bước

1. **Tạo thứ gì đó**: gõ `tạo file fizzbuzz.py in 1..100, chạy thử luôn` → agent viết + chạy + báo kết quả.
2. **Cho agent ngữ cảnh**: `@src/app.py` chèn file vào câu hỏi; kéo-thả ảnh vào ô chat để nói về ảnh.
3. **Hoàn tác**: lượt xong thấy sai → `/undo` (hoặc nút undo) quay về bản chụp trước; `/fork` tách nhánh làm song song.
4. **Tìm web**: bật **Web search** trong ⚙ → Kết nối → Model & generation; Forge thêm `:online` cho các lượt chat (phí theo provider).
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
- **Provider key** lưu tại `data/provider-secrets.json`; **connector token** lưu riêng tại `data/secrets.json`. Cả hai đều nằm ngoài git/ZIP, listing chỉ hiện bản mask.
- Shell/hook/background/git/LSP không thừa kế provider/admin key. MCP chỉ nhận secret được khai báo explicit trong `env` của server đó.

### Account và release mode (v0.35)

1. Operator chạy `python scripts/setup_keys.py --provider openrouter --release` (hoặc `--provider google`) **trước khi phát hành**. Nếu chưa có user, setup hỏi email + password admin đầu tiên.
2. Tạo thêm user bằng `python scripts/setup_auth.py --email member@example.com`, hoặc admin vào **⚙ → Team → Tạo / mời user**. Password ≥16 ký tự chỉ lưu PBKDF2 hash trong `data/auth.db`; không có username chung.
3. **Public signup là tùy chọn, mặc định tắt.** Admin bật **⚙ → Team → Cho phép tự đăng ký tài khoản member**. Màn hình login khi đó có mục **Đăng ký**; tài khoản mới luôn là member và tự đăng nhập sau khi tạo. Endpoint có CSRF + rate-limit theo IP/email. Email/password tự đăng ký chưa xác minh quyền sở hữu email qua SMTP.
4. Google OIDC được cấu hình trong Team. Nếu public signup tắt, Google chỉ cho user đã được tạo trước; nếu đang bật, email Google mới cũng chỉ tạo member. Google login chỉ dùng scope OIDC, không cấp Gmail.
5. Cookie session là HttpOnly; mutation cần CSRF. Logout/disable revoke session. User A không đọc được session/workspace/audit/inbox của user B.
6. Member chọn canonical model theo session; chỉ admin đổi default/settings/Team/signup/MCP/connectors/global skills. Release khóa key settings toàn server qua terminal.
7. CORS mặc định same-origin và có rate-limit LLM/auth/signup. Khi qua mạng **bắt buộc HTTPS reverse proxy**, đặt `FORGE_PUBLIC_URL=https://...` hoặc `FORGE_COOKIE_SECURE=1`; đọc `SECURITY.md` và `DEPLOY.md`.
8. Local chỉ listen `127.0.0.1`; chỉ đặt `FORGE_HOST=0.0.0.0` sau khi auth/proxy sẵn sàng. Owner ACL không phải OS sandbox; public signup cần gateway quota/CAPTCHA phù hợp khi mở Internet.
9. Nâng cấp từ v0.33: session cũ bị ẩn cho tới khi chạy dry-run rồi `python scripts/migrate_sessions.py --email admin@example.com --apply` tường minh.

## 10. Sự cố thường gặp

| Hiện tượng | Xử lý |
|---|---|
| Cửa sổ bat nháy rồi tắt | Chạy trong PowerShell: `py -3 scripts\launch.py` — đọc lỗi thật |
| "Python not found" | Cài lại Python, **tick "Add python.exe to PATH"**, mở PowerShell mới thử lại |
| Chữ lỗi font trong terminal | `chcp 65001` trước khi chạy |
| Cổng 8000 bận | `$env:FORGE_PORT=8010` rồi chạy lại bat (hoặc tắt tiến trình cũ) |
| Lỗi 402/429 từ model | Hết credit / quá tốc độ OpenRouter — nạp tiền hoặc đổi model (`/model`); agent có fallback tự động |
| Tưởng API key biến mất sau Save | Từ v0.36, mở ⚙ → Kết nối và xem **Trạng thái API key các provider**. Ô password luôn trống để không trả secret thô; `đã lưu` mới là trạng thái thật. Chọn đúng provider; để trống rồi Save không xoá key |
| Prompt đã lưu nhưng không có phản hồi/lỗi | Nâng lên v0.38.0: bản cũ có thể xoá SSE error khi reload timeline; bản mới giữ cảnh báo và chặn empty assistant. Chạy `.\.venv\Scripts\python.exe scripts\diagnose_llm.py --provider openrouter` (hoặc `--provider google`) để xem HTTP + response đã redact. **Đã lưu key không đồng nghĩa key hợp lệ** — cần Kiểm tra key rồi Save |
| `HTTP 501` khi tiếp tục Agent | Đọc endpoint + chi tiết trong banner mới. Nếu chi tiết từ provider nói không hỗ trợ request, đổi model có tool calling; Direct/tắt Effort chỉ để chẩn đoán vì Agent cần tools. Nếu body rỗng, chụp banner và copy dòng request 501 trong terminal Forge — chưa suy ra root cause chỉ từ status |
| `SSE ... kết thúc trước event done` | Stream bị cắt giữa chừng hoặc server dừng; kiểm tra terminal/proxy timeout rồi thử lại. Bản mới không coi stream cụt là thành công |
| MCP server báo `error` | `/mcp` đọc dòng error — thường là thiếu biến môi trường (đặt lại rồi `/mcp refresh`) |
| OAuth mở trang không xong | Chạy lại `/connectors oauth …`; công ty chặn popup thì dán URL vào tab mới |
| `.venv` hỏng / cài lỗi | Xoá thư mục `.venv` → chạy lại `run_forge.bat` |
| Muốn reset sạch | Xoá `data/` (mất phiên) — skill nằm ở `~/.forge` nên không mất |

## 11. Cập nhật & gỡ

- **Cập nhật**: `git pull` (hoặc giải nén bản mới đè lên) → chạy lại `run_forge.bat` (tự cài deps mới nếu có).
- **Gỡ**: xoá thư mục forge-agent + xoá `~/.forge` (skill toàn cục) nếu muốn sạch tuyệt đối. Không có gì cài ngầm vào hệ thống.

## Phụ lục — Lệnh slash hay dùng

`/help` · `/new` · `/sessions` · `/use <sid>` · `/model <tên>` · `/key <key>` · `/mode <agent|plan|direct>` · `/undo` · `/fork` · `/init` · `/review` · `/diff` · `/repomap [budget]` · `/doctor` · `/audit [n]` · `/export` · `/mcp [refresh]` · `/connectors add|auth|remove|oauth` · `/loop <giây> <việc>` · `/loop stop` · `/run <alias> <việc>` · `/msg <sid> <nội dung>` · `/inbox` · `/memory`
