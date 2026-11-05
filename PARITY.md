# ⚖ PARITY — Forge v0.9.0 vs Claude Code 2.1 / Codex CLI / OpenCode

> Là bản cập nhật của FEATURE_AUDIT.md (audit gốc chụp ở v0.6).
> Cột cuối cho biết **thay đổi gì qua 3 phiên bản v0.7 → v0.8 → v0.9**.
> Chú thích: ✅ có · 🟡 một phần · ❌ chưa có · ⛔ cố tình không làm · ⭐ độc quyền của Forge

---

## A. Lõi agent — v0.6: ~85% → **v0.9: ~95%**

| Tính năng | Claude Code | Codex | OpenCode | Forge v0.6 | **Forge v0.9** | Ghi chú |
|---|:-:|:-:|:-:|:-:|:-:|---|
| Agent loop (tools + tự sửa lỗi) | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| File tools (read/write/edit/search) | ✅ | ✅ | ✅ | ✅ | ✅ | + editor GUI hơn cả 3 đối thủ |
| Shell exec trong workspace | ✅ | ✅ sandbox | ✅ | ✅ | ✅ | — |
| Chế độ làm việc | Plan + perm | 2 dial | Build/Plan/Ask | ✅ 4 chế độ | ✅ | — |
| **Chuyển chế độ trong TUI** | ✅ | ✅ | ✅ Tab | ❌ | ✅ **v0.7** | Ctrl+M xoay vòng 💬🤖📋 |
| Permission theo pattern lệnh | ✅ | ✅ | ✅ | 🟡 | ✅ **v0.8** | allow/deny glob trong Settings + config.json |
| Native sandbox | ➖ | ✅ mạnh nhất | 🟡 | 🟡 | 🟡 | guard + Docker tuỳ chọn — **vẫn yếu hơn trên Windows** |

## B. Bộ nhớ & ngữ cảnh — v0.6: ~35% ⚠️ → **v0.12: ~95%**

| Tính năng | Claude Code | Codex | OpenCode | Forge v0.6 | **Forge v0.12** | Ghi chú |
|---|:-:|:-:|:-:|:-:|:-:|---|
| File quy tắc dự án | CLAUDE.md | AGENTS.md | AGENTS.md | ✅ | ✅ | AGENTS.md > AGENTS.txt > CLAUDE.md |
| **`/init` tự sinh file quy tắc** | ✅ | ✅ | ✅ | ❌ P0 | ✅ **v0.7** | demo-mode khi chưa có key |
| CLAUDE.md fallback | — | ✅ | ✅ | ❌ | ✅ **v0.7** | — |
| Quy tắc global | ✅ | ✅ | ✅ | ❌ | ✅ **v0.7** | `data/AGENTS.md` (≤2000 ký tự) |
| **/compact + auto-compact** | ✅ | ✅ | ✅ | ❌ P0 | ✅ **v0.7** | LLM tóm tắt + tự nén ở 150k ký tự |
| /context (xem mức dùng context) | ✅ | ✅ | 🟡 | ❌ | ✅ **v0.10** | lệnh + chip 🧠 % + GET /context |
| Auto-memory (tự ghi nhớ) | ✅ MEMORY.md | ➖ | ➖ | ❌ | ✅ **v0.10** | tool `memory_save`, cap 8KB, nạp tự động |
| **@import trong file quy tắc** | ✅ | ➖ | ➖ | ❌ | ✅ **v0.12** | `@path` nạp đệ quy ≤5 tầng, bỏ qua code fence/span, chống vòng, cap 8KB/import |
| **`#` quick-memory** | ✅ | ➖ | ➖ | ❌ | ✅ **v0.12** | gõ «# nội dung» → ghi MEMORY.md ngay, không tốn LLM (cả 3 UI + demo) |
| /memory (xem bộ nhớ nạp) | ✅ mở editor | ➖ | ➖ | ❌ | ✅ **v0.12** | overview: quy tắc global/dự án + MEMORY.md kèm số liệu; `/memory clear` có .bak |

## C. An toàn & hoàn tác — v0.6: ~75% → **v0.9: ~97%**

| Tính năng | Claude Code | Codex | OpenCode | Forge v0.6 | **Forge v0.9** | Ghi chú |
|---|:-:|:-:|:-:|:-:|:-:|---|
| Approval tương tác trước lệnh | ✅ | ✅ | ✅ | ✅ | ✅ | web modal + TUI + CLI |
| Chế độ YOLO | ✅ | ✅ | ✅ | ✅ Auto | ✅ | — |
| **Checkpoints / undo** | ✅ Esc-Esc | ✅ | ✅ | ❌ P0 | ✅ **v0.7** | git-inner riêng, undo theo từng hành động |
| Phân loại lệnh nguy hiểm | ➖ | ➖ | ➖ | ⭐ | ⭐ | guard 3 mức + allow/deny + anti-loop — **chi tiết hơn cả 3 đối thủ** |

## D. Review & hiển thị — v0.6: ~50% → **v0.12: ~95%**

| Tính năng | Claude Code | Codex | OpenCode | Forge v0.6 | **Forge v0.12** | Ghi chú |
|---|:-:|:-:|:-:|:-:|:-:|---|
| **Diff view khi sửa file** | ✅ /diff | ✅ | ✅ inline | ❌ P0 | ✅ **v0.7+v0.10** | web: diff xanh/đỏ + badge ±dòng · TUI: diff inline rich |
| **/diff xem diff phiên** | ✅ | ✅ | ✅ | ❌ | ✅ **v0.12** | git repo (`git diff HEAD`) hoặc checkpoint phiên (file mới có trong diff, loại `.forge/`) |
| Streaming + reasoning | ✅ | ✅ | ✅ | ✅ | ✅ | web + TUI |
| **/review code review** | ✅ /code-review | ✅ | ✅ | ❌ | ✅ **v0.12** | built-in: nhúng diff thật vào prompt chuẩn Codex (6 tiêu chí bug, P0–P3, verdict, loại pre-existing, "ưa không-finding hơn finding yếu") — chạy plan mode; custom command vẫn đè được |
| Xác thực key có sẵn | ➖ | ➖ | ➖ | ⭐ | ⭐ | /keycheck + 401/402 tiếng Việt |

## E. Mở rộng — v0.6: ~40% → **v0.11: ~95%**

| Tính năng | Claude Code | Codex | OpenCode | Forge v0.6 | **Forge v0.11** | Ghi chú |
|---|:-:|:-:|:-:|:-:|:-:|---|
| MCP | ✅ | ✅ | ✅ | ✅ 2 transport | ✅ **+ elicitation v0.9** | đủ theo spec 2026-07-28 (auto-decline secret) |
| Custom slash commands (file md) | ✅ | ✅ | ✅ | ❌ P1 | ✅ **v0.8** | `.forge/commands/` + global, $ARGUMENTS; v0.11: không có placeholder → nối args cuối |
| Custom agents (md + frontmatter) | ✅ | ➖ | ✅ | ❌ P1 | ✅ **v0.10** | `.forge/agents/<tên>.md` + `/run <tên>` 3 UI |
| Subagents ngữ cảnh riêng | ✅ | ✅ | ✅ | 🟡 | ✅ **v0.11** | tool `spawn_subagent` — phiên mới, workspace dùng chung cha, chống đệ quy (depth), events 🧩 trên 3 UI |
| Skills (SKILL.md model-invoked) | ✅ | ➖ | ✅ | ❌ P2 | ✅ **v0.11** | `.forge/skills/<tên>.md` — progressive disclosure: system prompt chỉ nạp name+description, LLM tự đọc body khi cần; `disable-model-invocation` ẩn khỏi block |
| Hooks (lifecycle scripts) | ✅ | ➖ | 🟡 | ❌ P2 | ✅ **v0.11** | `pre_tool_use` (exit 2 = chặn) / `post_tool_use` (nối nhận xét) / `session_start` (context, cache 1 lần/phiên); matcher regex; stdin JSON chuẩn |
| Plugins JS | ➖ | ➖ | ✅ | ❌ P2 | ⛔ | cố tình không (rủi ro > lợi ích) |
| **LSP (type realtime)** | ✅ qua IDE | ➖ | ✅ | ❌ P2 | ✅ **v0.9+v0.11** | diagnostics sau edit (v0.9) + điều hướng: definition / references / workspace symbols (v0.11, tự retry khi server chưa index) |
| Web search tool | ➖ | ✅ | 🟡 | ❌ P1 | ✅ **v0.8** | OpenRouter `:online`, có cảnh báo phí |
| Image input | ✅ | ✅ | 🟡 | ❌ P1 | ✅ **v0.8** | 📎 ≤4 ảnh, content-parts chuẩn OpenRouter |
| @file references | ➖ | 🟡 | ✅ | ❌ P1 | ✅ **v0.8** | ≤5 file × 40KB, chống traversal |

## F. Phiên & vận hành — v0.6: ~70% → **v0.9: ~82%**

| Tính năng | Claude Code | Codex | OpenCode | Forge v0.6 | **Forge v0.9** | Ghi chú |
|---|:-:|:-:|:-:|:-:|:-:|---|
| Nhiều phiên + resume | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| **Fork phiên** | ➖ | ✅ | ✅ | ❌ P1 | ✅ **v0.8** | copy messages + workspace; dự án thật dùng chung |
| Headless/script mode | ✅ -p | ✅ exec | ✅ run | ✅ --once | 🟡 | thiếu output JSON structured (P2) |
| Mở project bất kỳ | ✅ | ✅ | ✅ | ✅ | ✅ | gate FORGE_ALLOW_OPEN |
| **/export hội thoại** | ✅ | ➖ | ✅ | ❌ P1 | ✅ **v0.8** | Markdown (web tải file · TUI/CLI /export) |
| Share link công khai | ✅ | ✅ | ✅ | ⛔ | ⛔ | nguyên tắc no-cloud |
| Token/cost tracking | ✅ /cost | ✅ | 🟡 | ✅ | ✅ | theo phiên + toàn hệ thống |
| /doctor chẩn đoán | ✅ | ➖ | ➖ | 🟡 | 🟡 | keycheck kỹ, chưa có doctor tổng quát |

## G. Giao diện & đa nền tảng — v0.6: ~75% → **v0.9: ~90%**

| Tính năng | Claude Code | Codex | OpenCode | Forge v0.6 | **Forge v0.9** | Ghi chú |
|---|:-:|:-:|:-:|:-:|:-:|---|
| Terminal TUI đẹp | ✅ | ✅ | ✅ | ✅ | ✅ | 4 panel + modal duyệt + modal elicitation |
| Web UI tự host có editor | ✅ cloud | ✅ cloud | 🟡 desktop | ⭐ | ⭐ | explorer + editor + **terminal tích hợp** — hơn cả 3 đối thủ |
| REPL đơn giản | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Lệnh cài vào PATH | ✅ claude | ✅ codex | ✅ opencode | ✅ forge | ✅ | + build exe 3 OS |
| Themes | ✅ | ➖ | ✅ nhiều | ❌ P2 | ❌ | **còn thiếu** |
| **Model tuỳ ý (BYOK)** | ❌ Anthropic-only | ❌ OpenAI-first | ✅ 75+ | ⭐ | ⭐ | **450+** đồng bộ kèm giá + lọc free |
| **⚔ Battle mode** | ❌ | ❌ | ❌ | ⭐ | ⭐ | **duy nhất trên thị trường** |
| Sub-agent song song | ✅ | ✅ worktrees | ➖ | ✅ | ✅ | + battle per-model workspace |

---

## 📊 Điểm tổng (so với "daily driver" thực thụ)

| Nhóm | v0.6 (audit) | **v0.9** | Đã đóng khoảng trống bằng |
|---|:-:|:-:|---|
| A. Lõi agent | ~85% | **~95%** | TUI mode switch, permission patterns |
| B. Bộ nhớ & ngữ cảnh | ~35% ⚠️ | **~95%** | /init, /compact+auto, global rules, auto-memory, **@imports + # quick-memory (v0.12)** |
| C. An toàn & hoàn tác | ~75% | **~97%** | checkpoints/undo git-inner |
| D. Review & hiển thị | ~50% | **~95%** | diff view 3 UI, **/review + /diff built-in (v0.12)** |
| E. Mở rộng | ~40% | **~95%** | @file, commands, ảnh, web search, LSP diag+nav, elicitation, **skills + hooks + subagent (v0.11)** |
| F. Phiên & vận hành | ~70% | **~82%** | fork, /export |
| G. Giao diện | ~75% | **~90%** | elicitation form, diff, settings mở rộng |
| **TỔNG** | **≈ 62%** | **≈ 93%** | 18 hạng mục v0.7–v0.9 + 10 gap v0.10 + 4 mở rộng v0.11 + bộ nhớ/review v0.12 |

## 🟡 Còn thiếu — cập nhật v0.10 "Gap Closer" (10/10 đã xử lý)

> **✅ CẬP NHẬT v0.10:** cả 10 mục dưới đây đã được làm hoặc cải thiện ở mức hợp lý:

1. **~~/context~~ → ✅ v0.10** — lệnh `/context` (TUI/CLI) + chip 🧠 % context ở footer web + endpoint `/api/sessions/{sid}/context`
2. **~~Auto-memory~~ → ✅ v0.10** — tool `memory_save`: agent tự ghi bài học vào `MEMORY.md` (nạp tự động vào mọi phiên sau, cap 8KB, chống trùng)
3. **~~Diff inline TUI~~ → ✅ v0.10** — tool card TUI render diff +xanh/−đỏ ngay dưới kết quả (cap 40 dòng)
4. **~~Custom agents~~ → ✅ v0.10** — `.forge/agents/<tên>.md` (frontmatter description/model/mode) → `/run <tên> <task>` trên cả Web/TUI/CLI
5. **~~LSP navigation~~ → ✅ v0.11** — v0.10 có `lsp_diagnostics` + `lsp_symbols`; v0.11 thêm đủ bộ điều hướng: `lsp_definition`, `lsp_references`, `lsp_search_symbols` (tự retry khi server chưa index cross-file)
6. **~~Sandbox Windows~~ → 🟡 v0.10** — không thể "native sandbox" như Codex trên Windows, thay bằng **network kill-switch** (`block_network: true` chặn curl/pip/git push… ở mức danger) — sandbox thật vẫn là Docker
7. **~~Skills / Hooks~~ → ✅ v0.11** — v0.10: `on_file_change` + skills-as-commands; v0.11: hooks đủ vòng đời `pre_tool_use` (exit 2 = chặn tool call) / `post_tool_use` / `session_start` theo chuẩn Claude Code; skills đúng nghĩa SKILL.md model-invoked với progressive disclosure
8. **~~Themes~~ → ✅ v0.10** — 3 theme web (Tối / ☀ Sáng / 🌌 Amber CRT), chọn trong ⚙ Settings, lưu localStorage
9. **~~Headless JSON~~ → ✅ v0.10** — `forge --once "task" --json` → JSON structured {session, text, tools, usage, error} cho script/CI
10. **~~/doctor~~ → ✅ v0.10** — 11 mục chẩn đoán (Python/git/key/model/compact/LSP/MCP/guard/dữ liệu/hook) qua lệnh `/doctor` (TUI/CLI) + nút 🩺 trong ⚙ Settings

## 🚀 v0.11 "Extensibility Complete" — đủ 4 mục cuối của bảng E

| # | Tính năng | Cách dùng |
|---|---|---|
| 1 | **Skills model-invoked** | `.forge/skills/<tên>.md` với frontmatter `description` (≤200 ký tự — là *trigger duy nhất* để LLM tự kích hoạt) + `disable-model-invocation: true` để chỉ gọi tay `/<tên>`. **Progressive disclosure**: system prompt chỉ nạp name+description (~100 tokens/skill), LLM đọc body file khi cần — không đốt context |
| 2 | **Hooks vòng đời đầy đủ** | config `hooks: {pre_tool_use, post_tool_use, session_start}` (`.forge/config.json` hoặc global): script nhận JSON trên stdin (`{session_id, tool_name, tool_input, workspace}`), **exit 2 ở pre_tool_use = chặn tool call** (stderr trở thành lý do cho LLM), post nối nhận xét vào output, session_start trả context bổ sung (cache 1 lần/phiên). Matcher regex (`"write_file\|edit_file"`, bỏ trống = tất cả), timeout 30s |
| 3 | **Sub-agent delegation** | tool `spawn_subagent(task, model?)`: tạo phiên mới với **context hoàn toàn riêng** nhưng **workspace dùng chung cha**; chống đệ quy (sub-agent không có spawn_subagent); events 🧩 (started/progress/done) trên Web + TUI; kết quả tóm tắt quay về agent chính |
| 4 | **LSP navigation** | `lsp_definition` / `lsp_references` / `lsp_search_symbols` — đi tới định nghĩa, tìm nơi dùng, tra symbol toàn workspace (tự retry khi server chưa index xong cross-file; báo thân thiện nếu server không hỗ trợ) |

Kết quả test: **5/5 smoke v0.11 + regression 16/16 v0.7 + 12/12 v0.8 + 8/8 v0.9 + 9/9 v0.10 + TUI + e2e server**.

## 🧠 v0.12 "Memory & Review" — nốt 2 mục yếu cuối (B + D)

| # | Tính năng | Cách dùng |
|---|---|---|
| 1 | **@imports** | Trong `AGENTS.md`/`MEMORY.md` ghi `@docs/standard.md` → nội dung được nạp đệ quy (≤5 tầng, chống vòng lặp), bỏ qua bên trong code fence và inline code, cap 8KB/import — tách bộ nhớ lớn thành nhiều module |
| 2 | **`#` quick-memory** | Gõ `# luôn dùng pytest -q` → ghi vào MEMORY.md ngay lập tức, không gọi LLM, không tốn token (web + TUI + CLI, kể cả demo mode) |
| 3 | **/memory** | Xem đúng những gì đang nạp: quy tắc global/dự án (+số @import), MEMORY.md kèm số ghi nhớ + entry gần nhất; `/memory clear` xoá (còn .bak) |
| 4 | **/review** | Review diff thật (git repo: `HEAD`/file/`A...B`; không repo: checkpoint của phiên) theo prompt chuẩn Codex: 6 tiêu chí bug, P0–P3, Verdict APPROVE/COMMENT/REQUEST_CHANGES, loại bug pre-existing — chạy plan mode (không sửa code) |
| 5 | **/diff** | Xem diff phiên hiện tại trên cả 3 UI — TUI tô màu, web render markdown diff |

Kết quả test: **5/5 smoke v0.12 + regression 16/16 v0.7 + 12/12 v0.8 + 8/8 v0.9 + 9/9 v0.10 + 5/5 v0.11 + TUI + e2e server** (tổng 55 test).

## 🔀 v0.13 "Multi-Model Orchestrator" — đa model đúng chuẩn ngành

Research đầy đủ trong `MULTI_MODEL.md` (Claude Code subagent model routing · Anthropic
multi-agent research system · RouteLLM/FrugalGPT/OpenRouter). 5 mục đã làm:

| # | Tính năng | Chi tiết |
|---|---|---|
| 1 | **Alias model** | `spawn_subagent(model: 'cheap'\|'strong'\|'inherit'\|ID)` — cấu hình qua `model_roles` trong config; mặc định cheap = `openrouter/free`, strong = model phiên |
| 2 | **Routing guidance** | Spec tool nhúng bảng "việc đọc/tìm kiếm → cheap · code → inherit · kiến trúc/audit → strong" + nhắc fan-out khi có nhiều việc độc lập |
| 3 | **Fan-out song song** | Nhiều `spawn_subagent` trong cùng lượt chạy `asyncio.gather`-style (queue + `asyncio.wait`), tối đa 3 cùng lúc — events 🧩 về UI realtime |
| 4 | **Cap chống phình** | Tối đa **6 sub-agent/lượt** (thừa → báo giới hạn cho LLM tự hoàn thiện); vẫn cấm đệ quy |
| 5 | **Availability fallback** | Lỗi 402/429/5xx → thử model dự phòng (`model_fallbacks`, mặc định `openrouter/free`) đúng 1 lần + event `🔁` trên cả 3 UI — tách bạch khỏi quality routing |

## 🤖 v0.14 "Autonomy & Cost" — tự chủ hơn + thấy được tiền

Theo GAP_ANALYSIS.md (research Claude Code/OpenCode/Aider 2026) — 5 mục P0:

| # | Tính năng | Chi tiết |
|---|---|---|
| 1 | **🌐 Tool fetch_url** | LLM tự đọc URL (docs/API) → text 20KB; **chặn SSRF** (localhost/IP riêng/metadata, cả redirect); strip HTML bỏ script/style |
| 2 | **⚡ Shell nền** | `run_background` → id · `check_background` (output MỚI kể từ lần xem, không lặp) · `kill_background`; buffer đuôi 60KB, tối đa 8 running; guard danger vẫn chặn |
| 3 | **📋 Todo checklist** | tool `todo_write` (pending/doing/done) → event realtime → Web render thẻ tiến độ ✓/▶/◻, TUI/CLI in danh sách; LLM tự cập nhật trong vòng lặp |
| 4 | **💵 Chi phí $** | usage × giá OpenRouter (cache 1h) → chip 💵 footer web + dòng TUI/CLI + cộng dồn phiên; thiếu giá/mất mạng → ẩn, không lỗi |
| 5 | **⏳ Hàng đợi tin nhắn** | gõ Enter khi agent đang chạy → xếp hàng, tự gửi khi lượt xong; pill ⏳ có nút ✕ gỡ |

Kết quả test: **5/5 smoke v0.14 (chạy 2 lần, chống flaky) + regression 16+12+8+9+5+5+7 = 67 test xanh**.

## 🧩 v0.15 "Skills 2.0" — theo chuẩn mở Agent Skills (SKILL.md)

Theo SKILLS_RESEARCH.md (chuẩn agentskills.io — 70+ nền tảng, quyên cho Linux Foundation 10/2026):

| # | Mục | Chi tiết |
|---|---|---|
| 1 | **📦 Format chuẩn** | `<tên>/SKILL.md` (+ scripts/ references/ assets/) — tương thích ngược file dẹt v0.11; frontmatter YAML thật (pyyaml + fallback tự-quote giá trị có `:`); fields name/license/compatibility/metadata/allowed-tools |
| 2 | **🗂 Đa vị trí quét** | `.forge/skills` + `.agents/skills` (cross-client) + `.claude/skills` (project) + `~/.forge/skills` (user) + legacy global; project đè user + cảnh báo "bị che"; lenient validation (warn vẫn nạp, chỉ bỏ khi thiếu description/YAML vỡ) + diagnostics |
| 3 | **🛠 Tooling** | `/skills` (listing nhóm nguồn + chẩn đoán) · `/skills add <git-url\|owner/repo\|thư-mục>` (clone → validate → cài `~/.forge/skills`) · `/skills new <tên>` (scaffold đúng chuẩn) · `/skills remove`; skill mẫu `skills-samples/commit-vn`; `/<tên>` gọi được skill ở MỌI nguồn |

**Bằng chứng hệ sinh thái:** `/skills add anthropics/skills` cài 1 phát được 13 skill chính thức của Anthropic (docx, pdf, pptx, xlsx, skill-creator, mcp-builder…), 13/13 pass validate.
Test: **6/6 smoke v0.15 (×2) + regression 67 xanh (tổng 73)**.

## ⭐ 4 điểm Forge hơn/nhất thị trường

1. **⚔ Battle mode** — cùng 1 prompt chạy N model side-by-side: **không ai có**
2. **BYOK 450+ model** đồng bộ kèm giá + lọc free (Claude Code/Codex khoán nhà cung cấp)
3. **Web UI tự host đầy đủ** explorer + editor + terminal tích hợp
4. **Guard 3 mức + allow/deny + keycheck** — an toàn chi tiết hơn cả 3 đối thủ

## ⛔ Cố tình không theo

Share link cloud (nguyên tắc no-cloud) · IDE extension · autocomplete · plugins JS
