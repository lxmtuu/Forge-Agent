# 📋 TỔNG KẾT DỰ ÁN FORGE AGENT — mọi thứ đã làm

> Cập nhật: 2026-11-05 · Phát hành hiện tại: **v0.34.0 "Private team + multi-provider"** · 196 test / 30 suite · mypy 0 lỗi · 38 files · bandit Medium+ 0
> Lịch sử v0.10 → v0.34 chi tiết: **PROJECT_AUDIT.md** (mỗi vòng 1 mục) + **PARITY.md**. Tài liệu chính cho người dùng: README · USER_GUIDE · MCP_CATALOG · QUICKSTART · SECURITY.

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
| **v0.32.0** | `3e754aa` | **Autonomy nâng cao**: sub-agent nền + Notification `agent_completed`, repo map + `/repomap`, thêm 4 hook events; đóng A4/A5/C1 |
| **v0.33.0** | `994beda` | **Shared-server security**: sanitized subprocess env, terminal setup OpenRouter/Google/custom, provider secret store + PBKDF2 release auth, Settings lock, CORS same-origin, auth/LLM rate-limit. 179 test tại mốc này |
| **v0.34.0** | main (release) | **Private team + multi-provider**: per-user cookie auth + CSRF, email/password + Google OIDC, Team admin, owner ACL toàn bộ dữ liệu, canonical model theo session, provider-aware demo/cost/fallback/sub-agent, migration CLI và first-run bootstrap. 17 regression mới; toàn bộ 196 test PASS |

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
| `session.py` | Phiên bền vững + owner_id + ScopedSessionStore ACL + workspace/pointer/fork |
| `auth.py` | SQLite users/browser sessions/Google identities/OAuth flows; password/session chỉ hash, revoke/disable, dummy verify |
| `google_auth.py` | Google OIDC Authorization Code + PKCE/state/nonce, RS256/JWKS; chỉ scope OIDC |
| `models.py` | Canonical model registry/capabilities + ModelRouter stateless theo từng request |
| `config.py` | Provider-aware config + secret migration + profiles + release/rate-limit settings |
| `secrets.py` | Provider secret store ngoài git/ZIP, PBKDF2 password hash, sanitized child environment |
| `mcp.py` | MCP client stdio + HTTP, namespace tools, elicitation/create bidirectional |
| `elicitations.py` | Registry elicitation: accept/decline/cancel, auto-decline secret, required check |
| `lsp.py` | LSP client (pylsp/pyright/ts-server), publishDiagnostics debounce, format cho LLM |
| `atfiles.py` | @file references (≤5×40KB, chống traversal, bỏ binary) |
| `commands.py` | Custom slash commands `.forge/commands/*.md` + global, $ARGUMENTS |
| `export.py` | Xuất hội thoại Markdown |
| `llm.py` | OpenAI-compatible SSE cho OpenRouter/Google/custom, canonical prefix, provider-aware fallback/check_key, redact credential trong error |

### 🖥 4 giao diện
| Giao diện | Điểm mạnh riêng |
|---|---|
| **Web** (`server/` + `web/`) | Login email/password + Google có điều kiện, auth bootstrap trước data, cookie/CSRF wrapper, reset state khi đổi user, Team admin, model canonical theo session; SSE chat/battle, terminal/files, diff, elicitation, settings theo role, ảnh 📎, fork/export/undo/nén/init |
| **TUI** (`tui/`) | Toàn màn hình textual: 3 panel (sessions/chat/files), Ctrl+M đổi mode, mọi lệnh slash, modal duyệt + elicitation |
| **CLI** (`cli/`) | REPL rich + `--once` + `--parallel` + `--battle` + `--profile`, mọi lệnh slash |
| **Demo mode** | Không cần key vẫn chạy tool thật (kịch bản mẫu) — người mới bật là chạy |

### 🌐 Server API (nhóm chính)
`/api/health` · `/api/auth/{me,login,logout,users,password,google/*}` · `/api/settings` (GET/POST: key, model, mode, web_search, allow/deny, max_tokens) · `/api/keycheck` · `/api/models` (canonical multi-provider; live OpenRouter + Gemini direct) · `/api/sessions` CRUD · `/api/sessions/{sid}/chat` (SSE) · `/undo` `/compact` `/init` `/fork` `/export` · `/api/batch` · `/api/battle` (SSE) · `/api/approvals/{aid}` · `/api/elicitations` + `/api/elicitation/{eid}` · `/api/workspace/{exec,open,close,tree,file,upload,export}` · `/api/mcp` CRUD

---

## 3. Kiểm thử (release gate)

| Gate | Phạm vi | Kết quả |
|---|---|:-:|
| Full clean regression | 30 suite `scripts/test_*.py`, sau khi xoá `__pycache__` | **196/196 PASS** ✅ |
| `scripts/test_v033.py` | Secret store/hash, 3 providers, sanitized subprocess env, API redaction, cookie login/public health, release lock, CORS/preflight, rate-limit, terminal setup | **12/12** ✅ |
| `scripts/test_v034.py` | AuthStore, anonymous/CSRF, email login/logout, Team, owner ACL, audit/usage/inbox/approval/elicitation, migration, registry/routing, concurrent providers, background owner, OIDC + RS256/JWKS local, image fail-closed, setup CLI/Web bundle, provider-specific demo/cost, member MCP/skills, first-run launcher | **17/17** ✅ |
| HTTP smoke thật | Uvicorn :8765 + release mode + fake users/data tạm: cookie Secure/HttpOnly, CSRF, login/logout, SSE demo, Team/owner ACL, model theo session | **22/22 PASS** ✅ |
| Browser smoke thật | Playwright Chromium: admin Team, đổi/persist model qua chat+reload, logout/login member, ẩn admin tabs, browser storage/runtime | **14/14 PASS** ✅ |
| Static checks | mypy `server/main.py` + `engine/`; TypeScript noEmit; Vite production build 42 modules | **PASS** ✅ |
| Security lint | bandit Medium+ trên engine/server/setup/migration/launcher | **0 finding** ✅ |
| Ruff | Full cho new files; changed-core gate ngoại trừ legacy `BLE001/S110/S112/RUF100`; không tuyên bố toàn repo sạch | **PASS theo phạm vi** ✅ |

Bundle cuối: `server/static/assets/index-DUXriFRs.js` + `index-DvwSMss-.css`.

Bug Phase 1 bị test bắt và đã sửa: demo dùng active provider global thay vì provider của model; battle dùng chung một demo boolean; background sub-agent mất router/owner default; architect đổi semantics TUI; demo bỏ ảnh vẫn đòi vision; `ScopedSessionStore` thiếu `allow_mcp`; launcher thiếu Authlib và còn kiểm tra shared release password. Các failure do fixture response shape/logout 204 được sửa ở test/smoke client, không nới product ACL.

**Chưa kiểm chứng:** Docker/container smoke (sandbox không có Docker CLI) và Google OAuth thật bằng client production. OIDC đã kiểm bằng flow giả + JWT RS256/JWKS local; không dùng credential thật trong regression.

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
| `SECURITY.md` | Private-team threat model, owner ACL, cookie/CSRF, OIDC, provider/MCP boundary, migration/rotation và checklist |
| `scripts/demo_mcp_server.py` | MCP server mẫu (4 tools, có elicitation thật để thử) |

## 6. Trạng thái bàn giao

- **Release:** v0.34.0, Web production build sẵn; ZIP `forge-agent-v0.34.0.zip`.
- **Git:** nhánh main, release commit tạo từ working tree đã kiểm; baseline v0.33 `994beda` giữ nguyên.
- **Kiểm thử:** 196/196 test · 30 suite · HTTP 22/22 · browser 14/14 · mypy 0 lỗi · bandit Medium+ 0.
- **Preview smoke:** uvicorn :8765, health 0.34.0, release mode + data/tài khoản giả, không có provider credential thật.
- **Yêu cầu hệ thống:** Python 3.10+ · dependencies trong requirements (gồm Authlib) · OpenRouter/Google Gemini/custom provider hoặc demo không cần key.
- **Giới hạn đã ghi rõ:** single process/VPS; owner ACL không phải OS sandbox; chưa có image-generation adapter; real Google OAuth và Docker smoke là bước vận hành còn lại.
