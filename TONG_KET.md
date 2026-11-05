# 📋 TỔNG KẾT DỰ ÁN FORGE AGENT — mọi thứ đã làm

> Cập nhật: 2026-11-05 · Phát hành hiện tại: **v0.32.0 "Autonomy nâng cao"** · 167 test / 28 suite · mypy 0/33 file · bandit Medium+ 0
> Lịch sử v0.10 → v0.32 chi tiết: **PROJECT_AUDIT.md** (mỗi vòng 1 mục) + **PARITY.md**. Tài liệu chính cho người dùng: README · USER_GUIDE · MCP_CATALOG · QUICKSTART.

---

## 1. Lịch sử phiên bản

| Phiên bản | Commit | Nội dung chính |
|---|---|---|
| **v0.1** | `a0811ff` | Nền tảng: engine agent (OpenRouter BYOK) + CLI + web UI + safety guard + MCP client (stdio) + đóng gói deploy |
| **v0.2** | `fa89a30` | Sub-agent song song, upload/xuất zip workspace, đồng bộ 450+ model OpenRouter, theo dõi tokens/cost, CLI đủ tính năng |
| **v0.3** | `b141fa5` | Chế độ duyệt lệnh tương tác (ask mode) + MCP HTTP transport |
| v0.3.1 | `df5151d` | Fix sập Windows charmap (mọi I/O ép UTF-8) |
| v0.3.2 | `50a9d7e` | Kiểm tra key thật qua `/api/v1/auth/key` + hướng dẫn 401 thân thiện |
| v0.3.3 | `88f7800` | Xử lý 402 hết credit + lọc model free + setting max_tokens |
| **v0.4.0** | `1b60c1d` | Đại tu UI/UX từng pixel + gia cố logic agent (anti-loop, scroll fix) |
| **v0.5.0** | `5d24837` | Lệnh `forge` desktop-grade: TUI toàn màn hình (textual) + đóng gói pyproject/PyInstaller |
| **v0.6.0** | `01c56b2` | 4 chế độ làm việc 💬🤖📋⚔ (direct/agent/plan/battle) + terminal tích hợp + mở dự án thật + AGENTS.md + OS-rules |
| — | `94dae43` | **FEATURE_AUDIT.md**: so sánh 34 hạng mục vs Claude Code 2.1 / Codex / OpenCode → verdict ~62%, chỉ ra 5 lỗ hổng P0 |
| **v0.7.0** | `24304f6` | **Comfort Sprint** — xóa sổ 5 P0: diff view, checkpoints/undo, /compact+auto, /init, TUI Ctrl+M (+ CLAUDE.md fallback, global rules) |
| **v0.8.0** | `7a12ab9` | **Extensibility**: @file refs, custom slash commands, fork phiên, /export Markdown, ảnh vision, web search `:online`, permission patterns |
| **v0.9.0** | `bb62c9c` | **Intelligence**: LSP diagnostics (tự sửa lỗi sau khi ghi file), MCP elicitation đầy đủ (spec 2026-07-28), profiles kiểu config.toml |
| **v0.32.0** | bản hiện tại | **Autonomy nâng cao**: sub-agent nền + Notification `agent_completed`, repo map + `/repomap`, thêm 4 hook events; đóng A4/A5/C1. Các bản v0.10–v0.31: xem PROJECT_AUDIT.md |

---

## 2. Tính năng theo thành phần

### 🧠 Engine (`engine/`)
| Module | Chức năng |
|---|---|
| `agent.py` | Vòng lặp agent đầy đủ: stream, tool calls, chat modes, auto-compact, @file, content-parts, sub-agent nền + hook events |
| `tools.py` | Bộ tool lõi + diff/checkpoint + LSP + repo map + quản lý sub-agent nền |
| `repomap.py` | Bản đồ file/symbol nén gọn, rank tham chiếu chéo, budget + cache, auto-nạp workspace nhỏ |
| `guard.py` | Phân loại lệnh safe/warn/danger + allow/deny patterns + Docker sandbox tùy chọn |
| `approvals.py` | Hỏi duyệt lệnh tương tác (ask mode), auto-deny timeout |
| `checkpoints.py` | Checkpoint git-inner repo riêng, undo theo từng hành động |
| `session.py` | Phiên bền vững + workspace riêng + pointer dự án thật + fork |
| `config.py` | Config JSON + profiles + auto-compact + max_tokens + web_search |
| `mcp.py` | MCP client stdio + HTTP, namespace tools, elicitation/create bidirectional |
| `elicitations.py` | Registry elicitation: accept/decline/cancel, auto-decline secret, required check |
| `lsp.py` | LSP client (pylsp/pyright/ts-server), publishDiagnostics debounce, format cho LLM |
| `atfiles.py` | @file references (≤5×40KB, chống traversal, bỏ binary) |
| `commands.py` | Custom slash commands `.forge/commands/*.md` + global, $ARGUMENTS |
| `export.py` | Xuất hội thoại Markdown |
| `llm.py` | OpenRouter SSE client, 401/402 hướng dẫn tiếng Việt, resolve_model `:online`, check_key |

### 🖥 4 giao diện
| Giao diện | Điểm mạnh riêng |
|---|---|
| **Web** (`server/` + `web/`) | 30+ API endpoints, SSE streaming, chat + chips mode + battle side-by-side, terminal + file manager, diff xanh/đỏ, form elicitation, settings đầy đủ (key/model/mode/web search/patterns/MCP), ảnh 📎, fork/export/undo/nén/init |
| **TUI** (`tui/`) | Toàn màn hình textual: 3 panel (sessions/chat/files), Ctrl+M đổi mode, mọi lệnh slash, modal duyệt + elicitation |
| **CLI** (`cli/`) | REPL rich + `--once` + `--parallel` + `--battle` + `--profile`, mọi lệnh slash |
| **Demo mode** | Không cần key vẫn chạy tool thật (kịch bản mẫu) — người mới bật là chạy |

### 🌐 Server API (nhóm chính)
`/api/health` · `/api/settings` (GET/POST: key, model, mode, web_search, allow/deny, max_tokens) · `/api/keycheck` · `/api/models` (450+ OpenRouter) · `/api/sessions` CRUD · `/api/sessions/{sid}/chat` (SSE) · `/undo` `/compact` `/init` `/fork` `/export` · `/api/batch` · `/api/battle` (SSE) · `/api/approvals/{aid}` · `/api/elicitations` + `/api/elicitation/{eid}` · `/api/workspace/{exec,open,close,tree,file,upload,export}` · `/api/mcp` CRUD

---

## 3. Kiểm thử (tất cả PASS trước khi giao)

| Bộ test | Số test | Phạm vi | Kết quả |
|---|:-:|---|:-:|
| `scripts/test_v07.py` | 16 | Checkpoint roundtrip, diff cap, compact + auto-compact, /init demo, AGENTS.md fallback, server undo/compact/init, LLMError thân thiện | **16/16** ✅ |
| `scripts/test_v08.py` | 12 | @file (cap, binary, traversal), custom commands ($ARGUMENTS, frontmatter, global), fork độc lập, guard patterns, `:online`, content-parts ảnh, export, server endpoints | **12/12** ✅ |
| `scripts/test_v09.py` | 8 | Profiles merge, LSP thật với pylsp (lỗi→sạch), tool integration, elicitation registry + MCP e2e + agent event + server | **8/8** ✅ |
| `scripts/test_tui.py` | pilot | TUI mount, /help, demo turn | ✅ |
| E2E server thật | mỗi phiên bản | exec → undo → blocked → chat/battle SSE → fork/export → elicitation flow | ✅ |
| Regression | 36 | v0.7+v0.8 chạy lại trước khi phát hành v0.9 | **36/36** ✅ |

Bug thật đã bị test bắt trước khi ship (tiêu biểu): `git init` không tạo thư mục cha (checkpoints luôn fail) · unpack dict 2 giá trị (undo trả rác) · UnboundLocalError `text` trong SSE closure (v0.8) · pylsp publish gói rỗng trước gói lỗi (thêm debounce).

---

## 4. So sánh với đối thủ (FEATURE_AUDIT.md)

| Nhóm | v0.6 (audit) | Sau v0.9 |
|---|:-:|:-:|
| Lõi agent | ~85% | ~90% |
| Bộ nhớ & ngữ cảnh | ~35% | ~70% (compact/auto/checkpoint) |
| An toàn | ~75% | ~85% (permission patterns) |
| Review & self-correct | ~50% | ~70% (LSP diagnostics) |
| Mở rộng | ~40% | ~75% (@file, commands, fork, ảnh, web) |
| Phiên | ~70% | ~85% (fork, export) |
| Giao diện | ~75% | ~90% |
| **Tổng "daily-driver parity"** | **~62%** | **~80%** |

**Cố tình không theo** (ghi rõ trong audit): cloud share link, IDE extension, autocomplete, plugins JS.

---

## 5. Tài liệu đi kèm

| File | Nội dung |
|---|---|
| `README.md` | Toàn bộ tính năng 3 giao diện + bảng v0.7/v0.8/v0.9 + hướng dẫn + bảo mật |
| `QUICKSTART.md` | 5 phút chạy lần đầu (dành người mới, Windows) |
| `FEATURE_AUDIT.md` | Ma trận 34 hạng mục vs 3 đối thủ + cập nhật từng phiên bản |
| `PRODUCT_DIRECTION.md` | Kim chỉ nam sản phẩm (research đối thủ 2026) |
| `BUILD_DESKTOP.md` / `DEPLOY.md` | Đóng gói .exe / deploy server |
| `scripts/demo_mcp_server.py` | MCP server mẫu (4 tools, có elicitation thật để thử) |

## 6. Trạng thái bàn giao

- **Zip phát hành:** `forge-agent-v0.32.0.zip` (kèm web build sẵn)
- **Git:** nhánh main, release v0.32.0, working tree sạch tại thời điểm đóng gói
- **Kiểm thử:** 167/167 test · 28 suite · mypy 0/33 file · bandit Medium+ 0
- **Server demo:** uvicorn :8000, health OK (không cần key ở demo mode)
- **Yêu cầu hệ thống:** Python 3.10+ · `pip install -r` theo README · API key OpenRouter (hoặc chạy demo không cần key)
