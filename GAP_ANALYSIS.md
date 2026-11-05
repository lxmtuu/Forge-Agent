# 🔍 GAP ANALYSIS 2026 — tính năng thị trường vs Forge v0.13.2

> Ngày: 2026-11-04 · Nguồn: Claude Code changelog đến v2.1.316 + "Week 32/2026",
> OpenCode v1.19 vs Codex CLI v0.166 (morphllm/oflux/computingforgeeks 11-2026),
> Aider 2026 (repo-map, auto-commit, watch), tổng hợp 8-agent comparison (amux).
> Nguyên tắc: research → kiểm tra → test → sửa.

---

## 1. Forge ĐÃ CÓ (khẳng định lại — ngắn gọn)

Modes agent/plan/direct · guard 3 mức + allow/deny glob + block_network + Docker ·
checkpoint/undo/fork · compact + auto-compact · /init AGENTS.md · @file · ảnh ·
web search `:online` · MCP stdio/http + elicitation · LSP diagnostics + definition/
references/symbols · hooks pre/post/session_start · skills · commands · custom agents `/run` ·
subagents (song song ≤3, cap 6, alias model cheap/strong) · battle/batch · profiles ·
3 themes · Web/TUI/CLI + headless JSON · /doctor · /export · memory (@imports, `#`, /memory) ·
/review + /diff · model_fallback 402/429/5xx · autocomplete `/lệnh` + `@file` · Settings tabs.

## 2. CÒN THIẾU so với thị trường 2026 (có bằng chứng đối thủ có)

### Nhóm A — Tool & vòng lặp agent

| # | Tính năng | Ai có | Forge | Ưu tiên |
|---|---|---|---|---|
| A1 | **Tool `webfetch`** — LLM tự fetch 1 URL (đọc docs, API reference) | OpenCode (built-in + permission `webfetch`), Claude (WebFetch/WebSearch), Cline | ❌ chỉ search `:online`, không fetch URL chủ động | **P0** |
| A2 | **Tác vụ nền cho lệnh shell** — chạy dev server/test dài, không block; tool check output + kill | Claude (background tasks + Ctrl+B + auto-background MCP >2 phút), OpenCode (background subagents) | ❌ `run_command` block tới hết (timeout) | **P0** |
| A3 | **Todo/plan checklist** — LLM tự ghi danh sách việc, UI hiển thị tiến độ realtime (✓/◻) | Claude (TodoWrite/tasks), Codex (/goal) | ❌ | **P0** |
| A4 | **Sub-agent nền (background)** — lead tiếp tục làm, được báo khi sub xong (Notification agent_completed) | Claude v2.1.198 ⭐, OpenCode | ❌ spawn hiện chặn lượt | P1 |
| A5 | **Repo map** — bản đồ cấu trúc + symbol nén gọn tự nạp cho task lớn | Aider (tree-sitter), Claude ⚠️ | ❌ (nhưng có sẵn LSP symbols + tree để ghép) | P1 |
| A6 | **✅ ĐÃ LÀM v0.21** Architect 2-model — mode 🧭: model mạnh lập kế hoạch (không tool) → model rẻ thi công đủ tool | Aider architect mode | phase plan/execute stream riêng | P2 |

### Nhóm B — Git

| # | Tính năng | Ai có | Forge | Ưu tiên |
|---|---|---|---|---|
| B1 | **✅ ĐÃ LÀM v0.22** Auto-commit (opt-in) mỗi lượt — git init ngầm workspace, message Conventional Commits do model rẻ sinh (fallback heuristic), attribution 🤖 | Aider (signature), Codex (auto-PR) | /commit + /autocommit ở cả 3 UI | **P0** (opt-in) |
| B2 | Worktree isolation cho fork/subagent | Claude (/fork→worktree, isolation: worktree) | ❌ fork copy nguyên chỗ | P2 |

### Nhóm C — Hooks & sự kiện

| # | Tính năng | Ai có | Forge | Ưu tiên |
|---|---|---|---|---|
| C1 | **Thêm hook events**: `stop` · `user_prompt_submit` · `pre_compact` (exit 2 chặn nén) · `notification` | Claude (đủ bộ) | ❌ chỉ 3 events | P1 (nhỏ) |

### Nhóm D — Model & chi phí

| # | Tính năng | Ai có | Forge | Ưu tiên |
|---|---|---|---|---|
| D1 | **Chi phí $ theo phiên/lượt** — đã có giá từ /api/models + usage tokens → chỉ cần nhân | Claude (projected cost), Aider | ❌ chỉ hiện tokens | **P0** (nhỏ, giá trị cao) |
| D2 | **✅ ĐÃ LÀM v0.19** Local models — OpenAI-compatible base URL (Ollama/LM Studio) | Aider, OpenCode (75+ providers) | custom_base_url + custom_api_key (Ollama không cần key), cost tự ẩn | P1 |
| D3 | **✅ ĐÃ LÀM v0.22** Effort/reasoning budget — setting low/medium/high → payload reasoning.effort (chỉ OpenRouter) | Claude (--effort), OpenRouter reasoning | test bằng fake-OpenRouter chụp payload | P2 |

### Nhóm E — UX phiên

| # | Tính năng | Ai có | Forge | Ưu tiên |
|---|---|---|---|---|
| E1 | **Queue message khi agent đang chạy** — gõ tiếp được, tự gửi khi xong | Claude (queued messages) | ❌ chỉ có nút Dừng | **P0** |
| E2 | **✅ ĐÃ LÀM v0.19** /rename (tự đặt tên = tin nhắn đầu có sẵn) | Claude (/rename auto) | store.rename + POST /api/rename, 3 UI | P1 (nhỏ) |
| E3 | **✅ ĐÃ LÀM v0.19** Tìm phiên — sidebar (tiêu đề) + /find (tiêu đề+NỘI DUNG) | OpenCode | list(q) + ô 🔍 + /find | P1 (nhỏ) |
| E4 | **✅ ĐÃ LÀM v0.19** Thông báo khi xong — web Notification (tab ẩn) + TUI bell (>5s) | Claude (Notification hooks) | xin quyền lần gửi đầu | P1 (nhỏ) |
| E5 | **✅ ĐÃ LÀM v0.21** Edit lại tin người dùng → chạy lại từ đó (✏️ trên bubble, cắt timeline, /rerun + chat rerun=true) | chuẩn web chat | server cắt session, không append trùng | P2 |

### Nhóm F — Tự động hoá

| # | Tính năng | Ai có | Forge | Ưu tiên |
|---|---|---|---|---|
| F1 | **/loop — lịch định kỳ** (cron: dõi PR, chạy test mỗi giờ) | Claude (/loop, cron) | ❌ | P2 |
| F2 | Cross-session messaging (ListAgents/SendMessage) | Claude v2.1.224 | ❌ | P2 |

### ⛔ Cố tình không theo (giữ nguyên tắc no-cloud/BYOK — không đổi)

Share link cloud (OpenCode) · IDE extension/desktop app · plugins marketplace ·
Chrome/Computer Use/Voice/Remote control · cloud tasks (Codex/OpenAI) · OS-sandbox
seatbelt/Landlock (Windows-first → giữ Docker + block_network).

## 3. ✅ Gói v0.14 "Autonomy & Cost" (P0 — 5 mục) — ĐÃ TRIỂN KHAI

| Mục | Thiết kế phác thảo |
|---|---|
| A1 webfetch | tool `fetch_url(url)` — httpx GET ≤30s, strip HTML→text, cap 20KB; chặn SSRF (localhost/IP riêng/métadata), tuân guard danger khi ở mức cao; permission pattern `fetch_url` |
| A2 shell nền | tools `run_background(command)` trả task_id + `check_background(task_id)` + `kill_background(task_id)`; registry trong tiến trình, output cap vòng; sự kiện `background_done` |
| A3 todo | tool `todo_write(items[])` — lưu `.forge/todo.json`, event `todo_update` → 3 UI render checklist ✓/◻/▶; LLM tự cập nhật trong loop |
| D1 chi phí | tính `cost` từ usage × giá (/api/models cache) → chip 💵 web + /usage + export + battle so-cost |
| E1 queue | web: cho phép gõ khi streaming → hàng đợi; tự gửi khi `done` + badge "1 đang chờ" |

**Đã giao:** smoke 5/5 (2 lần liền) + regression 67 test xanh. Kỳ vọng ban đầu: agent **tự chủ nhiều hơn** (tự đọc tài liệu, tự chạy server nền, tự theo dõi
tiến độ) và người dùng **thấy được tiền + tiến độ** — 2 thứ đối thủ dùng để bán "autonomy".

## 4. Nguồn

- code.claude.com/docs/en/changelog (đến 14-07-2026) + whats-new/2026-w32 (cross-session messaging, /fork worktree)
- cc.bruniaux.com/releases (v2.1.198 background subagents ⭐, v2.1.49 worktree)
- help.apiyi.com Claude Code 2026-03 (/loop, 12 tính năng) · heyuan110.com (2026-02 worktree + background)
- morphllm.com/comparisons/opencode-vs-codex (11-2026: tools matrix, permission, sandbox)
- ofox.ai + composio.dev + computingforgeeks.com (4-agent comparison 2026)
- webidroid.com + dashen-tech.com + amux.io (Aider repo-map/auto-commit, 8-agent table)
- agentscamp.com (CLI agents 2026: git-native vs sandboxed)
