# ⚡ Forge Agent — AI Coding Agent tự host (kiểu Claude Code / Codex)

Forge là một coding agent **chạy trên máy bạn**: nó đọc/ghi/sửa file, tìm kiếm trong
codebase, chạy lệnh shell, tự kiểm chứng kết quả rồi tổng kết — y như Claude Code hay
Codex CLI, nhưng **bạn sở hữu toàn bộ** (engine + giao diện + dữ liệu).

Một engine duy nhất, **ba hình thái phần mềm** (chi tiết: BUILD_DESKTOP.md):

```
  forge            → TUI toàn màn hình trong terminal (kiểu OpenCode)
  forge --web      → Web UI (kiểu Claude Code web)
  forge --repl     → REPL dòng lệnh (kiểu Codex CLI)
  forge.exe        → file exe độc lập (build bằng PyInstaller/GitHub Actions)
```

```
                    ┌─────────────────────────┐
 Provider API     │      forge engine       │
◄──────────────────►│  agent loop + tools     │
 OpenRouter/Google│  sessions + workspace   │
                    └───────────┬─────────────┘
              ┌─────────────────┼──────────────────┐
              ▼                                    ▼
      cli/main.py (Rich TUI)              server/main.py (FastAPI)
      → dùng như Codex CLI                → SSE streaming + REST
                                           → web/ React UI (như Claude Code web)
```

## ✨ Tính năng (v1)

| Tính năng | CLI | Web |
|---|:-:|:-:|
| Streaming token-by-token | ✅ | ✅ |
| Hiển thị "suy nghĩ" (reasoning) | ✅ (dim stream) | ✅ (collapsible) |
| Tool cards: đọc/ghi/sửa file, search, chạy lệnh | ✅ | ✅ (collapsible) |
| Nhiều phiên (sessions) + workspace riêng từng phiên | ✅ | ✅ |
| **Sub-agent song song** (mỗi tác vụ 1 session + workspace) | ✅ `--parallel` | ✅ nút ⚡ Song song |
| **Upload file** vào workspace / **xuất zip** | — | ✅ (⬆ / ⤓) |
| **Đồng bộ 450+ model** từ OpenRouter (kèm giá/context) | ✅ `/model` | ✅ chip chọn model |
| **Theo dõi tokens/cost** theo phiên + toàn hệ thống | ✅ `/usage` | ✅ footer + Settings |
| Đổi model trực tiếp | ✅ `/model` | ✅ Settings |
| Demo mode (không cần API key) | ✅ `--demo` | ✅ tự kích hoạt |

**Tools có sẵn:** `list_dir` · `read_file` · `write_file` · `edit_file` ·
`search_files` (grep) · `run_command` (bash, timeout, giới hạn output) ·
**+ mọi tool từ MCP servers bên ngoài** (tự động namespace `mcp_<server>_<tool>`).

### 🎛 4 chế độ làm việc (v0.6)
| Chế độ | Hành vi |
|---|---|
| 💬 **Direct** | Chat thuần không tool — hỏi đáp nhanh, rẻ |
| 🤖 **Agent** | Vòng lặp đầy đủ: đọc/ghi file, chạy lệnh, tự sửa lỗi |
| 📋 **Plan** | Chỉ ĐỌC (list/read/search) + xuất kế hoạch chi tiết — không sửa gì; duyệt xong chuyển Agent thực thi (kiểu Cline/OpenCode Plan/Act) |
| ⚔ **Battle** | Cùng 1 prompt chạy song song trên tối đa 4 model, mỗi model 1 session+workspace, xem side-by-side rồi chọn phiên thắng cuộc (duy nhất ở Forge!) |

Kèm theo: **Terminal tích hợp** trong panel Files (bạn gõ lệnh chạy trực tiếp trong
workspace, vẫn qua guard), **AGENTS.md** (quy tắc dự án chuẩn Codex/OpenCode — đặt
file này vào workspace là agent tuân theo), và **mở dự án thật** làm workspace qua
`POST /api/workspace/open` (bật bằng env `FORGE_ALLOW_OPEN=1`).

### 🛋 Comfort (v0.7) — 5 lỗ hổng P0 trong FEATURE_AUDIT.md đã bị xóa sổ

| Tính năng | Web | TUI | CLI |
|---|---|---|---|
| **Diff view** — mỗi lần agent sửa file hiện diff xanh/đỏ + đếm ±dòng (kiểu PR) | ✅ tool card | — | — |
| **Checkpoints + Undo** — mọi write/edit/command tự chụp mốc git nội bộ; `↩ Undo` lùi workspace về mốc trước | ✅ nút | ✅ `/undo` | ✅ `/undo` |
| **/compact** — LLM tóm tắt hội thoại, giải phóng context | ✅ nút 🧹 | ✅ `/compact` | ✅ `/compact` |
| **Auto-compact** — phiên dài tự nén khi vượt ngưỡng (env `FORGE_AUTO_COMPACT`, mặc định 150000 ký tự, 0 = tắt) | ✅ | ✅ | ✅ |
| **/init** — phân tích workspace, sinh `AGENTS.md` (demo-mode khi chưa có key) | ✅ nút 🚀 | ✅ `/init` | ✅ `/init` |
| **TUI đổi chế độ chat** — `Ctrl+M` xoay vòng 🤖 agent / 📋 plan / 💬 direct | — | ✅ | ✅ `--mode` |
| Quy tắc dự án: `AGENTS.md` > `AGENTS.txt` > `CLAUDE.md` (fallback Claude Code) + global `data/AGENTS.md` | ✅ | ✅ | ✅ |

*Ghi chú Undo:* checkpoint nằm trong git-inner repo riêng `data/workspaces/.ckpt-*.git`
— không bao giờ đụng `.git` của dự án thật. Undo lùi đúng **1 hành động của agent**
(mỗi write/edit/command là 1 mốc); file sinh ra sau mốc sẽ bị xóa khi lùi qua mốc đó
(đúng ngữ nghĩa undo). Tắt bằng `checkpoints_enabled: false` trong `data/config.json`.

### 🧩 Extensibility (v0.8)

| Tính năng | Cách dùng |
|---|---|
| **@file references** | Gõ `@src/main.py` trong prompt (Web/TUI/CLI) — nội dung file được đính vào message (≤5 file × 40KB, tự bỏ file binary/path-traversal) |
| **Custom slash commands** | Tạo `.forge/commands/<tên>.md` trong dự án (hoặc `data/forge/commands/` toàn cục) → gõ `/<tên> [args]`; `$ARGUMENTS` được thay bằng args; frontmatter được bỏ qua |
| **🍴 Fork phiên** | Nút 🍴 (web) · `/fork` (TUI/CLI) — copy messages + workspace thành bản mới để thử hướng khác; phiên đang mở dự án thật → fork dùng chung dự án |
| **⤓ /export chat** | Nút ⤓ (web, tải .md) · `/export [file]` (TUI/CLI) — hội thoại ra Markdown (roles, tool calls, placeholder ảnh) |
| **🖼 Ảnh (vision)** | Nút 📎 (web) đính ≤4 ảnh png/jpeg/webp/gif — gửi OpenRouter dạng content-parts; demo mode bỏ qua có báo |
| **🌐 Web search** | Toggle trong ⚙ Settings — mọi lượt chat thêm suffix `:online` của OpenRouter (tìm web qua Exa, ~$4/1000 kết quả) |
| **Permission patterns** | ⚙ Settings: `allow_commands` (nâng warn→safe) & `deny_commands` (chặn tuyệt đối, ưu tiên cao nhất) — glob mỗi dòng 1 mẫu |

### 🔬 Intelligence (v0.9)

| Tính năng | Chi tiết |
|---|---|
| **LSP diagnostics** *(Claude-Code-style)* | Sau mỗi lần agent ghi/sửa file code, Forge hỏi language server và **đẩy lỗi vào cho LLM tự sửa ngay trong lượt** ("⛔ dòng 4: undefined name…"). Auto-detect: `pylsp`/`pyright-langserver` cho Python, `typescript-language-server` cho TS/JS — **không tự cài**. Bật: `py pip install "python-lsp-server[pyflakes,pycodestyle]"`. Tắt: `FORGE_LSP=0` hoặc `lsp_enabled: false`. Lỗi LSP không bao giờ làm hỏng tool call |
| **MCP elicitation** *(spec 2026-07-28)* | MCP server có thể **hỏi người dùng giữa chừng tool call** (`elicitation/create`): web hiện form (string/number/boolean), TUI hiện modal; trả lời accept/decline/cancel. An toàn: hiện rõ server nào hỏi; **form xin secret (password/api-key/…) bị tự động từ chối theo spec**; URL-mode không tự mở trình duyệt |
| **Profiles** *(Codex-style)* | `data/config.json` → `"profiles": {"safe": {"model": "...", "approval_mode": "guarded"}, "yolo": {...}}` → `forge --profile safe` hoặc lệnh `/profile safe` (TUI/CLI) — merge đè lên config gốc, không ghi đè file |

### 🧹 Gap Closer (v0.10) — 10 mục còn thiếu cuối cùng

| Tính năng | Dùng thế nào |
|---|---|
| **🧠 Auto-memory** | Agent tự gọi tool `memory_save` ghi bài học vào `MEMORY.md` → tự nạp vào mọi phiên sau (`/memory` xem) |
| **LSP tools chủ động** | `lsp_diagnostics` (kiểm tra 1 file) + `lsp_symbols` (cấu trúc hàm/lớp kèm dòng) — dùng được cả Plan mode |
| **Diff inline TUI** | Tool card TUI hiện diff +xanh/−đỏ ngay khi agent sửa file |
| **Custom agents** | `.forge/agents/<tên>.md` (frontmatter: description/model/mode) → `/run <tên> <task>` |
| **🩺 /doctor** | 11 mục chẩn đoán — `/doctor` (TUI/CLI) hoặc nút trong ⚙ Settings |
| **/context** | Mức dùng context: lệnh `/context` + chip 🧠 % ở footer web |
| **Hooks** | `"on_file_change": "black ."` trong config — chạy formatter/lint sau mỗi lần agent sửa file |
| **Network kill-switch** | `"block_network": true` — chặn mọi lệnh ra mạng (curl/pip/git push…) kể cả trên Windows |
| **Headless JSON** | `forge --once "task" --json` → JSON {session, text, tools, usage} cho script/CI |
| **Themes** | ⚙ Settings → 🌑 Tối / ☀ Sáng / 🌌 Amber CRT |

### 🚀 Extensibility Complete (v0.11) — mở rộng đúng chuẩn Claude Code

| Tính năng | Dùng thế nào |
|---|---|
| **🧩 Sub-agent** | Agent tự gọi `spawn_subagent(task)` cho việc nặng context (tìm kiếm diện rộng, review vùng code) — phiên mới, **workspace vẫn dùng chung**; trên web/TUI thấy thẻ 🧩 tiến độ realtime |
| **🛠 Skills chuẩn mở (SKILL.md)** | Thư mục `<tên>/SKILL.md` theo **chuẩn Agent Skills (agentskills.io)** — chạy được cả skill của Claude Code/Codex/OpenCode; quét `.forge/skills` + `.agents/skills` + `.claude/skills` + `~/.forge/skills`; quản lý bằng `/skills`, cài từ bất kỳ repo git nào bằng `/skills add owner/repo` |
| **🪝 Hooks vòng đời** | `data/config.json` → `"hooks": {"pre_tool_use": [{"command": "block-danger.sh", "matcher": "run_command"}], "post_tool_use": [...], "session_start": [...]}` — script nhận JSON trên stdin; **exit 2 = chặn tool call** (lý do stderr đi thẳng vào hội thoại) |
| **🧭 LSP navigation** | `lsp_definition` (đi tới định nghĩa) · `lsp_references` (tìm nơi dùng) · `lsp_search_symbols` (tra symbol toàn workspace) — tự retry khi server chưa index |

Ví dụ hook chặn lệnh nguy hiểm (`.forge/config.json` hoặc `data/config.json`):
```json
{
  "hooks": {
    "pre_tool_use": [
      { "command": "guard-hook.sh", "matcher": "run_command|write_file" }
    ],
    "session_start": [{ "command": "echo 'Dự án này dùng pytest và ruff'" }]
  }
}
```
Script hook đọc JSON từ stdin (`{"session_id", "tool_name", "tool_input", "workspace"}`); **exit 0 = cho qua, exit 2 = chặn** (stderr trở thành lý do LLM thấy); matcher là regex tên tool, bỏ trống = khớp tất cả.

### 🧠 Memory & Review (v0.12)

| Tính năng | Dùng thế nào |
|---|---|
| **# ghi nhớ nhanh** | Gõ `# luôn dùng pytest -q` ở khung chat → ghi vào `MEMORY.md` ngay, không tốn token LLM |
| **@imports** | Trong `AGENTS.md`: `@docs/standard.md` → nạp nội dung đệ quy (≤5 tầng, chống vòng, bỏ qua code block, cap 8KB/import) |
| **/memory** | Xem bộ nhớ đang nạp (quy tắc + MEMORY.md kèm số liệu) · `/memory clear` xoá (còn `.bak`) |
| **/review** | Code review diff thật: `git diff HEAD` (repo) hoặc checkpoint phiên — findings P0–P3 + Verdict, chạy read-only |
| **/diff** | Xem diff phiên hiện tại (TUI tô màu, web render markdown) |

```json
// AGENTS.md có thể tách module:
// "# Dự án X
@docs/api-rules.md
@docs/test-policy.md"
```

### 🔀 Multi-Model Orchestrator (v0.13)

| Tính năng | Dùng thế nào |
|---|---|
| **Sub-agent nhiều model** | Agent tự chọn: `spawn_subagent(task, model:'cheap')` cho việc đọc/tìm kiếm, `'strong'` cho kiến trúc/audit — alias cấu hình được |
| **Fan-out song song** | Giao nhiều việc độc lập trong 1 lượt → sub-agent chạy đồng thời (tối đa 3 cùng lúc, 6/lượt) |
| **Fallback tự động** | Model lỗi 402/429/5xx → tự thử model dự phòng, UI hiện dòng 🔁 |

```json
// data/config.json — vai trò model (tuỳ chọn)
{
  "model_roles": { "cheap": "openrouter/free", "strong": "anthropic/claude-sonnet-5.5" },
  "model_fallbacks": ["openrouter/free"]
}
```

### 🧩 Quản lý Skills trên web (v0.26)

⚙ → **🧩 Skills**: xem toàn bộ skill (project/user/built-in) kèm mô tả, 🔑 allowed-tools, cảnh báo diagnostics. Bấm **🔕 Cấm model gọi** khi không muốn model tự dùng một skill (đổi frontmatter `disable-model-invocation`, hiệu lực ngay); skill từ repo lạ hiện 🔒 — bấm **🔓 Tin skill này** để nạp. Cần đang mở một phiên (skills theo workspace).

### 📨 Nhắn tin giữa các phiên (v0.25)

Các phiên giờ trao đổi được: trong chat gõ `/msg <id-phiên> <nội dung>` (hoặc bảo agent dùng tool `send_message`) — phiên đích (vd phiên `/loop` đang chạy nền) thấy nhắc INBOX ở lượt kế tiếp và đọc bằng `check_inbox`. `/inbox` xem tin mới. Web có REST `POST/GET /api/sessions/{id}/messages`. Skill khai báo `allowed-tools` giờ hiện 🔑 trong `/skills`.

### 🌿 Worktree isolation (v0.24)

Bảo sub-agent làm việc trong **bản sao an toàn**: yêu cầu agent "dùng spawn_subagent với isolation=worktree" — sub sửa/xoá thoải mái mà workspace của bạn không đổi; xem diff trong báo cáo rồi quyết: `/worktree merge <phiên-con>` (gộp về) hoặc `/worktree discard <phiên-con>` (bỏ trắng). Fork phiên cũng nhanh hơn — xuất từ checkpoint nên không dính file đang ghi dở.

### 🔁 /loop + ⤓ Xuất audit (v0.23)

`/loop 30m <tác vụ>` — agent tự chạy lại tác vụ mỗi 30 phút (dõi PR, chạy test định kỳ…): CLI/TUI gõ trực tiếp, web gõ trong ô chat; `/loop off` để dừng. Mỗi nhịp là 1 lượt agent thật (tool + audit log + lưu phiên). Loop sống trong tiến trình — restart là dừng. Tab 📘 Audit có nút **⤓ Xuất CSV**.

### 📦 Auto-commit + 🧠 Reasoning effort (v0.22)

⚙ → **An toàn** → bật **Auto-commit mỗi lượt**: workspace tự `git init` ngầm, sau mỗi lượt agent có thay đổi sẽ commit với message Conventional Commits do model rẻ sinh (pattern Aider) — `git log` trong workspace thành lịch sử công việc. `/commit` commit thủ công; `/autocommit on|off` bật/tắt nhanh. ⚙ → **Kết nối** → **Effort suy luận** (Low/Medium/High) đặt budget reasoning cho model (chỉ qua OpenRouter).

### 🧭 Architect mode + ✏️ Sửa tin (v0.21)

Chip **🧭 Kiến trúc sư**: model mạnh lập kế hoạch → model rẻ tự thi công (đặt role trong `data/config.json`: `model_roles: {"strong": "...", "cheap": "..."}` — mặc định strong=model chính, cheap=openrouter/free). Hover tin nhắn của bạn → **✏️** sửa rồi Enter để chạy lại từ đó. Tab 🔗 Dịch vụ giờ cài/gỡ preset trực tiếp.

### 🔌 18 preset MCP (v0.29) — catalog đầy đủ trong MCP_CATALOG.md

6 gói phổ biến (Playwright · File System · Postgres · Github · Context7 · Sequential Thinking) + 7 mở rộng (**Stripe · Atlassian · Vercel · Supabase · Memory · Fetch · Brave Search**) + OAuth 2.1 (Notion/Sentry/Linear) + hub Composio 500+ app. Thêm nhanh `/connectors add <tên>` — biến môi trường resolve lúc spawn, đổi env xong `/mcp refresh` là ăn.

### 🔎 Visible provider errors + empty-response guard (v0.37.1)

- SSE `error` (401/402/501/provider/network) không còn bị `loadSession()` xoá ngay sau prompt; giữ cả prompt và diagnostic trên màn hình.
- Provider kết thúc với assistant rỗng không còn lưu `assistant: null` rồi im lặng. Forge báo model + `finish_reason`, gợi ý Direct/model khác/Max tokens theo trường hợp; completion bình thường vẫn lưu như cũ.
- `scripts/diagnose_llm.py` kiểm tra streaming trực tiếp bằng key đã lưu, không tools/session writes, chỉ in HTTP metadata + response đã redact. Windows: `.\.venv\Scripts\python.exe scripts\diagnose_llm.py --provider openrouter` (hoặc `--provider google`).
- `401 Missing Authentication header` là lỗi xác thực ở provider, không phải model đang suy nghĩ. Trạng thái **đã lưu** chỉ xác nhận có secret; phải **Kiểm tra key mới → Key hợp lệ → Lưu thay đổi**.

### 🎨 Responsive app shell + role-aware Settings (v0.37)

- **App gọn và rõ việc:** top bar hiển thị phiên hiện tại; mode, song song và model nằm trong một toolbar; footer chỉ giữ token/context và thao tác phiên. Empty state có ví dụ thao tác trực tiếp.
- **Workspace dùng được ở mọi kích thước:** panel cạnh chat trên desktop, drawer có nút đóng/scrim/Escape dưới 1100px. Sidebar mobile có nút đóng thật; session, thư mục và file đều dùng được bằng keyboard/touch, nút xoá không còn phụ thuộc hover.
- **Settings theo nhóm việc:** header/footer cố định, navigation riêng và nội dung cuộn độc lập; Connection tách **Provider & credentials** / **Model & generation**. Custom base URL chỉ hiện khi chọn provider Custom. Tab **Giao diện** cho mọi tài khoản; member thấy đúng các nhóm usable là Giao diện/Skills/Audit, admin giữ đủ global settings.
- **Logic được vá cùng UX:** blur model không đổi không gửi PATCH; response load session/tree/context đến muộn không ghi đè phiên mới; Max tokens invalid không đóng dialog như thể đã lưu; focus được giữ trong dialog và khôi phục khi đóng. ACL, CSRF, session revoke và secret server-side không thay đổi.
- Regression trình duyệt thật: `node scripts/browser_v037.cjs` (cần Playwright + smoke account giả; có thể đặt `FORGE_BASE_URL` và biến credential tương ứng).

### 🔑 Persistent provider keys/models + error diagnostics (v0.36)

- **Một key cho mỗi provider**, cả ba có thể cùng tồn tại: OpenRouter, Google Gemini direct và Custom OpenAI-compatible. Settings hiển thị trạng thái `đã lưu/chưa lưu` của đúng provider; ô password luôn trống khi mở lại vì server không trả secret thô. Đổi provider xoá draft key để tránh lưu nhầm.
- **Model theo session được lưu ngay** khi Enter/rồi ô, kể cả trước prompt đầu tiên. Đổi Model trong Settings lưu default + session hiện tại; Save key hoặc setting khác không reset model session. Phạm vi này không phải nhiều key cùng một provider.
- **Lỗi không còn bị nuốt:** HTTP error giữ status + endpoint + chi tiết đã redact; response rỗng được nói rõ; SSE kết thúc trước `done` báo mất kết nối thay vì im lặng. Các synthetic command cũng gửi `done`.
- Provider trả **501** được giải thích là model/endpoint có thể không hỗ trợ tool calling, streaming hoặc reasoning; thử model khác cho Agent, hoặc Direct/tắt Effort để chẩn đoán. Đây là chẩn đoán có kiểm soát, không khẳng định mọi HTTP 501 đã có cùng root cause.

### 🔐 Account, public signup tùy chọn + multi-provider routing (v0.35)

| Tính năng | Hành vi |
|---|---|
| **Account riêng** | Admin đầu tiên tạo bằng `scripts/setup_auth.py` hoặc `setup_keys.py --release`; admin mời member trong ⚙ → **Team**. Email/password + Google OIDC, không còn shared Basic/Bearer password |
| **Public signup opt-in (v0.35)** | Admin bật trong ⚙ → **Team** hoặc đặt `FORGE_ALLOW_REGISTRATION=1` làm default ban đầu. Form tự đăng ký chỉ tạo member, có CSRF + rate-limit theo IP/email, auto-login; mặc định tắt khi nâng cấp |
| **Cookie + CSRF** | Session cookie HttpOnly/SameSite=Lax/Secure qua HTTPS, DB chỉ lưu token hash; mutation và SSE POST cần CSRF. Logout/disable revoke session |
| **Owner ACL** | Session/workspace, fork/export, batch/battle/sub-agent, loop, inbox, audit/usage, approval/elicitation đều lọc theo user. Session legacy `owner_id=""` chỉ hiện sau `scripts/migrate_sessions.py --apply` tường minh |
| **Model theo session** | Canonical `openrouter:vendor/model`, `google:gemini-...`, `custom:...`; provider key chỉ ở server. Demo/cost/fallback/sub-agent route theo model của từng request, không mutate default toàn server |
| **Admin/member boundary** | Chỉ admin đổi settings/default/Team/MCP/connectors/global skills. Member vẫn chọn model và quản lý project workspace của mình, nhưng không nạp MCP credential toàn server |
| **Google OIDC** | Authorization Code + PKCE/state/nonce, RS256/JWKS; scope chỉ `openid email profile`, **không cấp Gmail/offline access** |
| **Release security** | Settings/keycheck toàn server khóa qua terminal; CORS same-origin mặc định, auth/LLM rate-limit, API `no-store`, sanitized subprocess env |
| **Image generation** | Mới có capability contract; chưa có adapter, API báo `image_generation_adapter=false` và request tạo ảnh trả 501 |

Các account vẫn chạy cùng OS account và provider quota; public signup không xác minh quyền sở hữu email qua SMTP và không thay thế gateway quota/CAPTCHA; đây là owner ACL ở application layer cho nhóm tin cậy, không phải OS sandbox chống user độc hại. Quy trình HTTPS, migration, Docker/systemd và checklist: **SECURITY.md · DEPLOY.md**.

### 🌙 Autonomy nâng cao (v0.32)

| Tính năng | Cách dùng và giới hạn |
|---|---|
| **Sub-agent chạy nền** | Trong Agent mode, yêu cầu agent dùng `spawn_background_agent(task)` — lead làm tiếp ngay; khi xong, tóm tắt tự vào hộp thư lead và hook `notification` nhận `agent_completed`. Theo dõi bằng `check_background_agents`. Tối đa 3 tác vụ đang chạy/phiên; `isolation=worktree` không tự merge. Registry trong tiến trình, restart là sạch |
| **Repo map kiểu Aider** | `/repomap [budget]` (CLI/TUI) hoặc tool `repo_map`: file + symbol Python/JS/TS/Go/Rust, xếp hạng theo tham chiếu chéo, cache theo nội dung/mtime. Workspace nhỏ (≤60 file, map ≤4.000 ký tự, không bị cắt) tự nạp vào system prompt; repo lớn gọi tool chủ động, budget 500–20.000 |
| **Thêm 4 hook events** | `user_prompt_submit` (exit 2 chặn prompt, không gọi LLM) · `pre_compact` (exit 2 chặn nén) · `stop` (cuối lượt) · `notification` (duyệt lệnh + sub-agent nền xong). Cấu hình cùng khối `hooks` hiện có; script nhận JSON qua stdin |

### 🚀 Chạy nhanh (v0.37)

Windows: **double-click `run_forge.bat`** — tự tạo .venv, tự cài deps, chạy server, mở trình duyệt. macOS/Linux: `./run_forge.sh`. Kiểm tra môi trường: `python scripts/launch.py --check`. Mới bắt đầu? Đọc **USER_GUIDE.md** — hướng dẫn tiếng Việt từng bước.

### 🔐 OAuth 2.1 cho connectors (v0.20)

Playwright (điều khiển browser, 25 tool) · File System (`FORGE_FS_DIR`=<thư mục>) · Postgres (`DATABASE_URL`=connection string, chỉ-đọc) · Github (`/connectors auth github <PAT>`) · Context7 · Sequential Thinking — thêm nhanh bằng `/connectors add <tên>`, xem tool bằng `/mcp`. Biến môi trường được resolve lúc server spawn — đổi env xong gõ `/mcp refresh`.

### 🔐 OAuth 2.1 cho connectors (v0.20)

Notion/Sentry/Linear giờ đăng nhập bằng tài khoản thật: tạo ứng dụng OAuth của nhà cung cấp (redirect `http://127.0.0.1:8765/callback`) → `/connectors add notion` → `/connectors oauth notion <client_id> <client_secret>` — trình duyệt mở, duyệt xong token tự lưu (PKCE + state chống CSRF, refresh ngầm). Trên web: ⚙ → tab **🔗 Dịch vụ**. Toàn bộ token chỉ nằm trong `data/secrets.json` (chmod 600), không bao giờ vào context LLM.

### 🖥 Model cục bộ (v0.19) — Ollama/LM Studio không cần key

⚙ Cài đặt → **Kết nối** → Provider **Custom OpenAI-compatible** → **Custom base URL**: `http://localhost:11434/v1` → Model: `llama3.2` (tên model cục bộ) → chat như OpenRouter. Xoá URL để quay lại OpenRouter. Tiện ích kèm theo: `/rename <tên>`, `/find <từ-khóa>` (tìm trong cả nội dung tin nhắn), ô 🔍 trên sidebar, thông báo desktop khi agent xong (tab ẩn).

### 📘 Audit log (v0.17.2)

Mọi tool call của agent (kể cả MCP, lệnh bị từ chối, hook chặn) được ghi `data/audit/<ngày>.jsonl` — token tự mask. Xem: `/audit [n]` trên cả 3 UI, hoặc tab **📘 Audit** trong ⚙ Cài đặt (web) — bảng + ô lọc realtime.

### 🔌 Connectors (v0.17) — nối SaaS qua MCP

```bash
/connectors                       # xem đã cài + presets sẵn sàng
/connectors add github            # GitHub chính thức (api.githubcopilot.com/mcp)
/connectors auth github <PAT>     # dán Personal Access Token (được mask, không lộ)
/connectors add playwright        # browser thật cho test E2E (stdio)
/connectors add composio-hub <url-từ-composio.dev>   # Gmail/Slack/Vercel — managed OAuth
/connectors allow github search_* # cho phép tool bỏ duyệt (mặc định: tool MCP phải duyệt)
```

Preset sẵn: `github` · `linear` · `supabase` (read_only) · `notion` · `sentry` · `figma-desktop` · `context7` · `playwright` · `composio-hub`.
Token lưu `data/secrets.json` (chmod 600), mask khi hiển thị, **không bao giờ** vào context của model.
Tool MCP chưa allowlist phải được bạn duyệt trước khi chạy (như lệnh shell).

### 🧩 Skills 2.0 (v0.15) — chuẩn mở Agent Skills

```bash
/skills                      # liệt kê mọi skill theo nguồn + chẩn đoán
/skills add anthropics/skills   # cài từ GitHub (owner/repo, URL git, hoặc thư mục local)
/skills new review-api Review API theo chuẩn dự án   # scaffold skill mới đúng spec
/commit-vn fix lỗi login     # gọi skill như slash command ($ARGUMENTS)
```

Nơi quét (project đè user): `.forge/skills/` · `.agents/skills/` · `.claude/skills/` · `~/.forge/skills/` · built-in `bundled-skills/` (skill-creator).
Skill có thể kèm `scripts/` `references/` `assets/` — agent chạy script qua shell (vẫn qua guard danger).
**An toàn**: skill nằm trong repo dự án phải được tin trước mới nạp cho model — `/skills trust` xem, `/skills trust <tên>` hoặc `/skills trust all` để chấp nhận (chống prompt injection từ repo lạ).
Skill mẫu: `skills-samples/commit-vn/`. Tạo skill mới: bảo agent *"tạo skill ..."* — nó theo skill-creator built-in.

### 🤖 Autonomy & Cost (v0.14)

| Tính năng | Dùng thế nào |
|---|---|
| **🌐 fetch_url** | Agent tự đọc URL (docs, API reference) — chặn SSRF, strip HTML |
| **⚡ Shell nền** | Agent chạy dev server/test dài mà không khoá phiên: `run_background` → `check_background` → `kill_background` |
| **📋 Todo** | Agent tự lập checklist tiến độ — thẻ 📋 ✓/▶/◻ realtime trên cả 3 UI |
| **💵 Chi phí** | Footer web + TUI hiện ~$ mỗi lượt và cộng dồn phiên (theo giá OpenRouter thật) |
| **⏳ Hàng đợi** | Enter khi agent đang chạy → tin nhắn xếp hàng, tự gửi khi xong |

Ví dụ `profiles` trong `data/config.json`:
```json
{
  "profiles": {
    "safe": { "model": "openrouter/free", "approval_mode": "guarded", "max_tokens": 8192 },
    "yolo": { "model": "anthropic/claude-sonnet-5.5", "approval_mode": "auto", "web_search": false }
  }
}
```


CLI/TUI: `forge --battle "prompt" --models m1 m2 m3` · `forge --once "..." --mode plan`.

Định hướng sản phẩm chi tiết: **PRODUCT_DIRECTION.md**.

Mọi đường dẫn file bị chặn thoát khỏi workspace của phiên; lệnh shell chạy với
timeout 30s (tối đa 120s) và output bị cắt ở 12k ký tự.

### 🛡 An toàn lệnh shell — 3 chế độ
- **Guarded** (mặc định): phân loại lệnh safe/warn/danger — lệnh nguy hiểm
  (`sudo`, `rm -rf /`, `curl | bash`…) bị **chặn** sẵn, agent phải giải thích.
- **🔔 Hỏi từng lệnh (ask)**: agent tạm dừng, hiện thẻ phê duyệt với lệnh + lý do;
  bạn chọn **Chấp nhận / Luôn cho phép lệnh này / Từ chối** (web hoặc terminal).
  Lệnh được "luôn cho phép" lưu vào phiên, lần sau không hỏi lại. Timeout 3 phút = tự từ chối.
- **Auto (YOLO)**: chạy mọi lệnh, rủi ro tự chịu.
- **Docker sandbox**: nếu máy có Docker, bật trong Settings để mọi lệnh chạy
  trong container `--network=none --memory=512m --cpus=1 --cap-drop=ALL`.

### 🔌 MCP client (mới)
Kết nối MCP server chuẩn (stdio JSON-RPC) — agent tự nhận thêm tool:
1. ⚙ Settings → MCP servers → thêm, VD server filesystem:
   `npx` + args `-y, @modelcontextprotocol/server-filesystem, /tmp/du-lieu`
2. Lưu lại → từ lượt chat kế tiếp, model thấy tool `mcp_fs_*` và dùng như tool thường.
3. Test nhanh có sẵn: `python3 scripts/demo_mcp_server.py` (echo/add/now_time),
   cấu hình mẫu trong `mcp.example.json`.
4. Trong CLI: `/mcp` xem trạng thái, `/mcp refresh` khởi động lại.

Hỗ trợ **2 transport**: `stdio` (subprocess) và **`http`** (Streamable-HTTP với
`Mcp-Session-Id`) — ví dụ trong `mcp.example.json`, server test HTTP:
`python -m uvicorn scripts.demo_mcp_http_server:app --port 8931`.

### ⚡ Sub-agent song song (mới)
Chạy nhiều tác vụ đồng thời, mỗi tác vụ một session + workspace riêng biệt:
```bash
# CLI
python cli/main.py --parallel "viết fizzbuzz" "tạo README" "viết hàm sqrt + test"
```
Web: bấm nút **⚡ Song song** cạnh ô nhập → mỗi dòng trở thành 1 tác vụ → Gửi.
Kết quả hiển thị theo nhóm Task 1/2/3… với trạng thái riêng từng task.

### 🔢 Theo dõi usage + đồng bộ model (mới)
- Tokens/cost tích luỹ theo phiên (CLI `/usage`, web footer) và toàn hệ thống (Settings).
- Danh sách model **tự đồng bộ từ OpenRouter** mỗi giờ — chọn model bằng chip có
  sẵn giá ($/M tokens) và context length.

## 🚀 Chạy

### Web
```bash
pip install -r requirements.txt
cd web && npm install && npm run build && cd ..   # build 1 lần
python scripts/setup_auth.py          # lần đầu: tạo admin, password nhập ẩn
uvicorn server.main:app --host 127.0.0.1 --port 8000
# mở http://localhost:8000
# hoặc: ./run_forge.sh  (tự cài + tự build + chạy)
# hoặc: docker compose up -d --build
```
Deploy VPS/PaaS chi tiết: **DEPLOY.md**.

### CLI / TUI
```bash
pip install -e .              # cài 1 lần → có lệnh `forge` trong PATH
forge                         # TUI toàn màn hình (khuyên dùng — kiểu OpenCode)
forge --repl                  # REPL đơn giản
forge --once "viết fizzbuzz rồi chạy test"
forge --parallel "task A" "task B"
forge --list-sessions
# hoặc không cài: python cli/main.py / python -m tui.launch
```

### Provider key (OpenRouter / Google Gemini)
```bash
python scripts/setup_keys.py --provider openrouter   # nhập ẩn trong terminal
# hoặc: python scripts/setup_keys.py --provider google
python scripts/setup_keys.py --check
```
Key lưu ở `data/provider-secrets.json` (chmod 600 khi hỗ trợ), không nằm trong `config.json`, git hoặc ZIP. Trên máy cá nhân vẫn có thể nhập qua ⚙ Settings hoặc `/key`; shared release khóa Web Settings.

OpenRouter: **https://openrouter.ai/keys** — một key dùng cho Claude, GPT, Gemini, DeepSeek, Qwen, Kimi… Google AI Studio: **https://aistudio.google.com/api-keys**. Environment/secret manager vẫn được hỗ trợ cho deployment; không ghi secret vào source hay shell history.

Model mặc định: `anthropic/claude-sonnet-5.5`. Đổi tuỳ thích trong Settings.
Model rẻ để test: `google/gemini-3.8-flash` hoặc `deepseek/deepseek-v4.1-flash`.

## 🏗️ Kiến trúc

```
forge-agent/
├── engine/               # lõi dùng chung — không phụ thuộc UI
│   ├── agent.py          # vòng lặp: LLM → tool_calls → thực thi → lặp (tối đa 30 vòng)
│   ├── llm.py            # OpenAI-compatible SSE: OpenRouter/Google/custom
│   ├── tools.py          # tool lõi + schema OpenAI + sandbox đường dẫn/timeout
│   ├── repomap.py        # repo map nén gọn, rank refs chéo + cache (v0.32)
│   ├── guard.py          # phân loại lệnh shell + Docker sandbox wrapper
│   ├── mcp.py            # MCP client (stdio JSON-RPC) + manager
│   ├── session.py        # phiên JSON: messages chuẩn OpenAI, workspace riêng
│   ├── secrets.py        # provider secret store + PBKDF2 + sanitized env
│   └── config.py         # provider/model, approval mode, thư mục data/
├── server/main.py        # FastAPI: /api/... + /api/mcp + static web build
├── cli/main.py           # Rich TUI, chạy chung engine
├── web/                  # React + Vite + TypeScript (không dùng UI framework)
├── scripts/demo_mcp_server.py  # MCP server mẫu để test
├── Dockerfile / docker-compose.yml / DEPLOY.md
└── data/                 # runtime ngoài git/ZIP: config, provider/auth secrets, sessions/
```

Sự kiện engine phát ra (CLI và web cùng tiêu thụ):
`reasoning_delta` · `assistant_delta` · `tool_start` · `tool_result` ·
`assistant_message` · `error` · `turn_end`.

## 🔐 Bảo mật — đọc trước khi exposing ra internet

- **Guarded mode** chặn sẵn các lệnh nguy hiểm nhất; bật **docker_sandbox** khi có
  Docker để cách ly hoàn toàn (không mạng, giới hạn tài nguyên).
- Shared/public server? Chạy **release mode**, đặt sau HTTPS reverse-proxy — checklist trong SECURITY.md + DEPLOY.md.
- Provider key không gửi full về browser (chỉ mask), không vào browser storage; subprocess bị sanitized env.
- Session/workspace đặt tên file an toàn (sanitize), đường dẫn bị chặn thoát root.

## 🗺️ Roadmap gợi ý

- [x] Guard phân loại lệnh + chế độ guarded/auto (giống approval mode của Codex)
- [x] Docker sandbox wrapper (tự kích hoạt khi có Docker)
- [x] MCP client — nối tool server bên ngoài (hệ sinh thái MCP)
- [x] Đóng gói deploy: Dockerfile + compose + DEPLOY.md (VPS/PaaS)
- [x] Tải file lên workspace, xuất zip
- [x] Sub-agent / chạy song song nhiều tác vụ
- [x] Đồng bộ model list tự động từ `openrouter.ai/api/v1/models` + theo dõi tokens
- [x] MCP transport HTTP (streamable, `Mcp-Session-Id`) — song song với stdio
- [x] Duyệt lệnh tương tác: chế độ **ask** hiện thẻ phê duyệt trước khi chạy lệnh warn/danger

---
*Được xây kèm audit của repo `cporter202/API-mega-list` — xem `AUDIT.md` để hiểu
bối cảnh và bài học thiết kế rút ra.*
