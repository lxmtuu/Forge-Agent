# 🔍 FEATURE AUDIT — Forge v0.6.0 vs Claude Code 2.1 / Codex CLI / OpenCode

> Ngày audit: 2026-11-04 · Nguồn: docs chính thức + cheat sheets mới nhất của 3 đối thủ,
> đối chiếu với toàn bộ code Forge (đã chạy 15/15 test engine + TUI pilot + web health).
> Chú thích: ✅ có · 🟡 một phần · ❌ chưa có · ⛔ cố tình không làm · ⭐ độc quyền của Forge

> **✅ CẬP NHẬT v0.7 — 5/5 P0 ĐÃ XỬ LÝ:** (1) Diff view xanh/đỏ trong tool card ·
> (2) `/compact` + auto-compact (env `FORGE_AUTO_COMPACT`, mặc định 150k ký tự) ·
> (3) Checkpoints/undo qua git-inner repo riêng · (4) `/init` sinh AGENTS.md (demo fallback) ·
> (5) TUI `Ctrl+M` đổi mode + `/undo` `/compact` `/init` `/perm` · kèm CLAUDE.md fallback +
> global `data/AGENTS.md`. Verify: 16/16 test `scripts/test_v07.py` + e2e server.
> Điểm "bộ nhớ/ngữ cảnh" nâng ~35% → ~70%; "giao diện" ~75% → ~85%.

> **✅ CẬP NHẬT v0.8 — extensibility (theo lộ trình bên dưới):** @file references
> (≤5 file×40KB, chống traversal) · custom slash commands `.forge/commands/*.md` +
> global (chuẩn OpenCode) · fork phiên (messages + workspace copy) · /export Markdown ·
> ảnh vision (📎 ≤4 ảnh, content-parts OpenRouter) · web search `:online` toggle ·
> permission patterns allow/deny trong Settings. Verify: 12/12 test `scripts/test_v08.py`
> + 16/16 regression v0.7 + e2e. Điểm "mở rộng" nâng ~40% → ~75%.

## 1. Bảng ma trận tổng (34 hạng mục)

### A. Lõi agent
| Tính năng | Claude Code | Codex | OpenCode | **Forge** |
|---|:-:|:-:|:-:|:-:|
| Agent loop (tools + tự sửa lỗi) | ✅ | ✅ | ✅ | ✅ |
| File tools (read/write/edit/search) | ✅ | ✅ | ✅ | ✅ + editor GUI |
| Shell exec trong workspace | ✅ | ✅ sandbox | ✅ | ✅ |
| Chế độ làm việc | Plan + perm modes | 2 dial: sandbox×approval | Build/Plan/Ask (Tab) | ✅ Direct/Agent/Plan + Guarded/Ask/Auto |
| **Chuyển chế độ trong TUI** | ✅ | ✅ | ✅ Tab | ❌ (chỉ web có chips) |
| Permission theo pattern lệnh | ✅ allow/deny | ✅ exec-policy | ✅ allow/ask/deny | 🟡 approve-always từng lệnh (chưa có config file) |
| Native sandbox (không mạng, giới hạn ghi) | ➖ | ✅ mạnh nhất | 🟡 | 🟡 guard + Docker tuỳ chọn (Windows yếu) |

### B. Bộ nhớ & ngữ cảnh
| Tính năng | Claude Code | Codex | OpenCode | **Forge** |
|---|:-:|:-:|:-:|:-:|
| File quy tắc dự án | CLAUDE.md | AGENTS.md (hierarchy) | AGENTS.md | ✅ AGENTS.md/AGENTS.txt |
| **`/init` tự sinh file quy tắc** | ✅ | ✅ | ✅ | ❌ |
| CLAUDE.md fallback | — | ✅ | ✅ | ❌ |
| Quy tắc global (~) | ✅ | ✅ | ✅ | ❌ |
| **/compact + auto-compact** | ✅ | ✅ | ✅ | ❌ **P0 — phiên dài sẽ tràn context** |
| /context (xem mức dùng) | ✅ | ✅ | 🟡 | ❌ |
| Auto-memory (tự ghi nhớ) | ✅ MEMORY.md | ➖ | ➖ | ❌ |

### C. An toàn & hoàn tác
| Tính năng | Claude Code | Codex | OpenCode | **Forge** |
|---|:-:|:-:|:-:|:-:|
| Approval tương tác trước lệnh | ✅ | ✅ | ✅ | ✅ (web modal + TUI modal + CLI prompt) |
| Chế độ YOLO | ✅ bypass | ✅ never+bypass | ✅ yolo | ✅ Auto |
| **Checkpoints / undo (revert file)** | ✅ Esc-Esc | ✅ | ✅ /undo /redo | ❌ **P0** |
| Phân loại lệnh nguy hiểm | ➖ | ➖ | ➖ | ⭐ guard 3 mức + anti-loop |

### D. Review & hiển thị
| Tính năng | Claude Code | Codex | OpenCode | **Forge** |
|---|:-:|:-:|:-:|:-:|
| **Diff view khi sửa file** | ✅ /diff | ✅ | ✅ inline | ❌ **P0** |
| Streaming + reasoning hiển thị | ✅ | ✅ | ✅ | ✅ (web + TUI) |
| /review code review | ✅ | ✅ | ✅ lệnh tuỳ chỉnh | ❌ |
| Xác thực key có sẵn | ➖ | ➖ | ➖ | ⭐ /keycheck + lỗi 401/402 thân thiện |

### E. Mở rộng
| Tính năng | Claude Code | Codex | OpenCode | **Forge** |
|---|:-:|:-:|:-:|:-:|
| MCP | ✅ | ✅ | ✅ | ✅ stdio + HTTP (thiếu elicitation/OAuth — P2) |
| Custom slash commands (file md) | ✅ | ✅ | ✅ | ❌ P1 |
| Custom agents (md + frontmatter) | ✅ | ➖ | ✅ | ❌ P1 |
| Subagents context riêng | ✅ | ✅ | ✅ General/Explore | 🟡 batch/battle (ngữ cảnh riêng nhưng không tự delegate) |
| Skills | ✅ | ➖ | ✅ | ❌ P2 |
| Hooks (lifecycle scripts) | ✅ | ➖ | 🟡 plugins | ❌ P2 |
| Plugins JS | ➖ | ➖ | ✅ | ❌ P2 |
| LSP (lỗi type realtime) | ✅ qua IDE | ➖ | ✅ | ❌ P2 |
| Web search tool | ➖ | ✅ --search | 🟡 Exa | ❌ P1 |
| Image input | ✅ | ✅ | 🟡 | ❌ P1 |
| @file references trong prompt | ➖ | 🟡 | ✅ | ❌ P1 |

### F. Phiên & vận hành
| Tính năng | Claude Code | Codex | OpenCode | **Forge** |
|---|:-:|:-:|:-:|:-:|
| Nhiều phiên + resume | ✅ | ✅ | ✅ | ✅ |
| Fork phiên | ➖ | ✅ | ✅ | ❌ P1 |
| Headless/script mode | ✅ -p | ✅ exec | ✅ run | ✅ --once (thiếu JSON out — P2) |
| Mở project bất kỳ | ✅ | ✅ -C | ✅ | ✅ (FORGE_ALLOW_OPEN gate) |
| /export hội thoại | ✅ | ➖ | ✅ | ❌ P1 (mới export workspace zip) |
| Share link công khai | ✅ web | ✅ cloud | ✅ /share | ⛔ cố tình không (không cloud) |
| Token/cost tracking | ✅ /cost | ✅ | 🟡 | ✅ theo phiên + toàn hệ thống |
| /doctor chẩn đoán | ✅ | ➖ | ➖ | 🟡 keycheck |

### G. Giao diện & đa nền tảng
| Tính năng | Claude Code | Codex | OpenCode | **Forge** |
|---|:-:|:-:|:-:|:-:|
| Terminal TUI đẹp | ✅ | ✅ | ✅ | ✅ Textual (sessions+chat+tree+status+modal) |
| Web UI tự host có editor | ✅ (cloud) | ✅ (cloud) | 🟡 desktop beta | ⭐ full: explorer + editor + **terminal tích hợp** |
| REPL đơn giản | ✅ | ✅ | ✅ | ✅ |
| Lệnh cài vào PATH | ✅ claude | ✅ codex | ✅ opencode | ✅ forge (+ build exe 3 OS) |
| Themes | ✅ | ➖ | ✅ nhiều | ❌ P2 |
| **Model tuỳ ý (BYOK)** | ❌ Anthropic-only | ❌ OpenAI-first | ✅ 75+ | ⭐ **450+ đồng bộ kèm giá + lọc free** |
| **⚔ Battle mode** | ❌ | ❌ | ❌ | ⭐ **duy nhất trên thị trường** |
| **⚡ Sub-agent song song** | ✅ | ✅ worktrees | ➖ | ✅ + battle per-model workspace |

## 2. Điểm tín nhiệm

| Nhóm | Tỷ lệ đạt |
|---|---|
| A. Lõi agent | **~85%** (thiếu: TUI mode switch, permission config file) |
| B. Bộ nhớ & ngữ cảnh | **~35%** ⚠️ yếu nhất — không có /compact, /init, auto-memory |
| C. An toàn | **~75%** (mạnh về guard, thiếu checkpoints/undo) |
| D. Review | **~50%** (thiếu diff view — đau nhất khi dùng thực tế) |
| E. Mở rộng | **~40%** (MCP tốt, còn lại chưa) |
| F. Phiên & vận hành | **~70%** |
| G. Giao diện | **~75%** + 3 điểm độc quyền |
| **TỔNG** | **≈ 62% so với "daily driver" thực thụ** — lõi đủ mạnh, lớp "cảm giác lâu dài" (context, undo, diff) còn thiếu |

## 3. Kết luận — Forge đang ở đâu?

**Đã đạt chuẩn**: vòng lặp agent, 6 tools, 4 chế độ, guard/approval 3 mức (chi tiết hơn
opencode), MCP 2 transport, TUI 4-panel, web UI có editor + terminal (hơn cả 3 đối thủ
ở mảng web tự host), BYOK 450+ model, Battle mode (không ai có), packaging `forge`/exe.

**Thiếu 5 thứ khiến nó "chưa giống Claude Code khi dùng thật"** (thứ tự ưu tiên):
1. **🟥 Diff view** — sửa file mà không thấy thay đổi xanh/đỏ → không kiểm soát được
2. **🟥 /compact + auto-compact** — phiên dài >50 lượt sẽ tràn context và "mất trí"
3. **🟥 Checkpoints/undo** — agent hỏng file là không quay lại được
4. **🟥 `/init`** — không tự sinh AGENTS.md, người dùng mới phải viết tay
5. **🟨 TUI thiếu chuyển chế độ** + CLAUDE.md fallback + rules global

**Không nên đuổi theo** (cố tình): share link cloud (nguyên tắc no-cloud), IDE extension,
autocomplete, plugins JS (rủi ro bảo mật > lợi ích ở quy mô này).

## 4. Lộ trình đề xuất (cập nhật)

- **v0.7 "Comfort sprint"** — 5 mục 🟥/🟨 ở trên:
  diff view (web + TUI), /compact (tóm tắt hội thoại qua LLM, giữ system+quy tắc),
  checkpoints (snapshot git nội bộ trước mỗi edit, /undo), /init sinh AGENTS.md,
  TUI mode switch (Ctrl+M), CLAUDE.md fallback + global rules file.
- **v0.8 "Extensibility sprint"**: @file refs, custom slash commands (.forge/commands/*.md),
  custom agents (.forge/agents/*.md), fork phiên, /export hội thoại, image input,
  web search tool (tối đa 1 provider), permission config file (JSON allow/deny patterns).
- **v0.9**: LSP readonly diagnostics, MCP elicitation, profiles (kiểu Codex config.toml).

*Xem chi tiết kiến trúc từng mục trong PRODUCT_DIRECTION.md.*
