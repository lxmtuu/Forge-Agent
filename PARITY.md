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

## B. Bộ nhớ & ngữ cảnh — v0.6: ~35% ⚠️ → **v0.9: ~72%**

| Tính năng | Claude Code | Codex | OpenCode | Forge v0.6 | **Forge v0.9** | Ghi chú |
|---|:-:|:-:|:-:|:-:|:-:|---|
| File quy tắc dự án | CLAUDE.md | AGENTS.md | AGENTS.md | ✅ | ✅ | AGENTS.md > AGENTS.txt |
| **`/init` tự sinh file quy tắc** | ✅ | ✅ | ✅ | ❌ P0 | ✅ **v0.7** | demo-mode khi chưa có key |
| CLAUDE.md fallback | — | ✅ | ✅ | ❌ | ✅ **v0.7** | — |
| Quy tắc global | ✅ | ✅ | ✅ | ❌ | ✅ **v0.7** | `data/AGENTS.md` (≤2000 ký tự) |
| **/compact + auto-compact** | ✅ | ✅ | ✅ | ❌ P0 | ✅ **v0.7** | LLM tóm tắt + tự nén ở 150k ký tự |
| /context (xem mức dùng context) | ✅ | ✅ | 🟡 | ❌ | ❌ | **còn thiếu** — chưa có lệnh xem |
| Auto-memory (tự ghi nhớ) | ✅ MEMORY.md | ➖ | ➖ | ❌ | ❌ | **còn thiếu** (chỉ global rules thủ công) |

## C. An toàn & hoàn tác — v0.6: ~75% → **v0.9: ~97%**

| Tính năng | Claude Code | Codex | OpenCode | Forge v0.6 | **Forge v0.9** | Ghi chú |
|---|:-:|:-:|:-:|:-:|:-:|---|
| Approval tương tác trước lệnh | ✅ | ✅ | ✅ | ✅ | ✅ | web modal + TUI + CLI |
| Chế độ YOLO | ✅ | ✅ | ✅ | ✅ Auto | ✅ | — |
| **Checkpoints / undo** | ✅ Esc-Esc | ✅ | ✅ | ❌ P0 | ✅ **v0.7** | git-inner riêng, undo theo từng hành động |
| Phân loại lệnh nguy hiểm | ➖ | ➖ | ➖ | ⭐ | ⭐ | guard 3 mức + allow/deny + anti-loop — **chi tiết hơn cả 3 đối thủ** |

## D. Review & hiển thị — v0.6: ~50% → **v0.9: ~72%**

| Tính năng | Claude Code | Codex | OpenCode | Forge v0.6 | **Forge v0.9** | Ghi chú |
|---|:-:|:-:|:-:|:-:|:-:|---|
| **Diff view khi sửa file** | ✅ /diff | ✅ | ✅ inline | ❌ P0 | 🟡 **v0.7** | web: ✅ diff xanh/đỏ + badge ±dòng · **TUI: chưa có diff inline** |
| Streaming + reasoning | ✅ | ✅ | ✅ | ✅ | ✅ | web + TUI |
| /review code review | ✅ | ✅ | ✅ lệnh tuỳ chỉnh | ❌ | 🟡 **v0.8** | tự làm được qua custom command (`.forge/commands/review.md`) — chưa built-in |
| Xác thực key có sẵn | ➖ | ➖ | ➖ | ⭐ | ⭐ | /keycheck + 401/402 tiếng Việt |

## E. Mở rộng — v0.6: ~40% → **v0.9: ~62%**

| Tính năng | Claude Code | Codex | OpenCode | Forge v0.6 | **Forge v0.9** | Ghi chú |
|---|:-:|:-:|:-:|:-:|:-:|---|
| MCP | ✅ | ✅ | ✅ | ✅ 2 transport | ✅ **+ elicitation v0.9** | đủ theo spec 2026-07-28 (auto-decline secret) |
| Custom slash commands (file md) | ✅ | ✅ | ✅ | ❌ P1 | ✅ **v0.8** | `.forge/commands/` + global, $ARGUMENTS |
| Custom agents (md + frontmatter) | ✅ | ➖ | ✅ | ❌ P1 | ❌ | **còn thiếu** — chưa làm .forge/agents |
| Subagents ngữ cảnh riêng | ✅ | ✅ | ✅ | 🟡 | 🟡 | batch/battle có context riêng nhưng chưa tự delegate |
| Skills | ✅ | ➖ | ✅ | ❌ P2 | ❌ | — |
| Hooks (lifecycle scripts) | ✅ | ➖ | 🟡 | ❌ P2 | ❌ | — |
| Plugins JS | ➖ | ➖ | ✅ | ❌ P2 | ⛔ | cố tình không (rủi ro > lợi ích) |
| **LSP (type realtime)** | ✅ qua IDE | ➖ | ✅ | ❌ P2 | 🟡 **v0.9** | diagnostics sau edit ✅ (tự sửa lỗi trong lượt) · chưa có tool điều hướng (goToDefinition…) |
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
| B. Bộ nhớ & ngữ cảnh | ~35% ⚠️ | **~72%** | /init, /compact+auto, CLAUDE.md fallback, global rules |
| C. An toàn & hoàn tác | ~75% | **~97%** | checkpoints/undo git-inner |
| D. Review & hiển thị | ~50% | **~72%** | diff view (web), custom /review |
| E. Mở rộng | ~40% | **~62%** | @file, commands, ảnh, web search, LSP diag, elicitation |
| F. Phiên & vận hành | ~70% | **~82%** | fork, /export |
| G. Giao diện | ~75% | **~90%** | elicitation form, diff, settings mở rộng |
| **TỔNG** | **≈ 62%** | **≈ 85%** | 18 hạng mục nâng hạng v0.7–v0.9 + 10 mục "còn thiếu" xử lý ở v0.10 |

## 🟡 Còn thiếu — cập nhật v0.10 "Gap Closer" (10/10 đã xử lý)

> **✅ CẬP NHẬT v0.10:** cả 10 mục dưới đây đã được làm hoặc cải thiện ở mức hợp lý:

1. **~~/context~~ → ✅ v0.10** — lệnh `/context` (TUI/CLI) + chip 🧠 % context ở footer web + endpoint `/api/sessions/{sid}/context`
2. **~~Auto-memory~~ → ✅ v0.10** — tool `memory_save`: agent tự ghi bài học vào `MEMORY.md` (nạp tự động vào mọi phiên sau, cap 8KB, chống trùng)
3. **~~Diff inline TUI~~ → ✅ v0.10** — tool card TUI render diff +xanh/−đỏ ngay dưới kết quả (cap 40 dòng)
4. **~~Custom agents~~ → ✅ v0.10** — `.forge/agents/<tên>.md` (frontmatter description/model/mode) → `/run <tên> <task>` trên cả Web/TUI/CLI
5. **~~LSP navigation~~ → 🟡 v0.10** — 2 tool mới: `lsp_diagnostics` (kiểm tra chủ động) + `lsp_symbols` (cấu trúc hàm/lớp kèm dòng); goToDefinition đầy đủ vẫn chưa có (LLM dùng symbols thay thế hiệu quả)
6. **~~Sandbox Windows~~ → 🟡 v0.10** — không thể "native sandbox" như Codex trên Windows, thay bằng **network kill-switch** (`block_network: true` chặn curl/pip/git push… ở mức danger) — sandbox thật vẫn là Docker
7. **~~Skills / Hooks~~ → 🟡 v0.10** — hooks: `on_file_change` trong config (chạy formatter/lint sau mỗi lần agent sửa file, output nối vào cho LLM thấy); skills: `.forge/skills/*.md` được nhận như commands
8. **~~Themes~~ → ✅ v0.10** — 3 theme web (Tối / ☀ Sáng / 🌌 Amber CRT), chọn trong ⚙ Settings, lưu localStorage
9. **~~Headless JSON~~ → ✅ v0.10** — `forge --once "task" --json` → JSON structured {session, text, tools, usage, error} cho script/CI
10. **~~/doctor~~ → ✅ v0.10** — 11 mục chẩn đoán (Python/git/key/model/compact/LSP/MCP/guard/dữ liệu/hook) qua lệnh `/doctor` (TUI/CLI) + nút 🩺 trong ⚙ Settings

## ⭐ 4 điểm Forge hơn/nhất thị trường

1. **⚔ Battle mode** — cùng 1 prompt chạy N model side-by-side: **không ai có**
2. **BYOK 450+ model** đồng bộ kèm giá + lọc free (Claude Code/Codex khoán nhà cung cấp)
3. **Web UI tự host đầy đủ** explorer + editor + terminal tích hợp
4. **Guard 3 mức + allow/deny + keycheck** — an toàn chi tiết hơn cả 3 đối thủ

## ⛔ Cố tình không theo

Share link cloud (nguyên tắc no-cloud) · IDE extension · autocomplete · plugins JS
