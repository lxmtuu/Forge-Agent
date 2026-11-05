# 📋 TỔNG KẾT DỰ ÁN FORGE AGENT — mọi thứ đã làm

> Cập nhật: 2026-11-06 · Phát hành hiện tại: **v0.38.0 "Bilingual Web UI"** · 228 test / 35 suite · Chromium UX 37/37 + English 23/23 + hotfix 1/1 · mypy 0 lỗi · 39 files · bandit Medium+ 0
> Lịch sử v0.10 → v0.37 chi tiết: **PROJECT_AUDIT.md** (mỗi vòng 1 mục) + **PARITY.md**. Tài liệu chính cho người dùng: [README](../../README.md) · [USER_GUIDE](../guides/USER_GUIDE.md) · [MCP_CATALOG](../guides/MCP_CATALOG.md) · [QUICKSTART](../guides/QUICKSTART.md) · [SECURITY](../guides/SECURITY.md).

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
| **v0.34.0** | `908683c` | **Private team + multi-provider**: per-user cookie auth + CSRF, email/password + Google OIDC, Team admin, owner ACL toàn bộ dữ liệu, canonical model theo session, provider-aware demo/cost/fallback/sub-agent, migration CLI và first-run bootstrap. 17 regression mới; toàn bộ 196 test PASS |
| **v0.35.0** | `7d1250a` | **Opt-in public signup + auth UX**: form đăng ký member, auto-login, admin toggle bền vững, CSRF + rate-limit IP/email, role injection guard, Google self-signup theo policy, trạng thái Google chưa cấu hình rõ ràng. 8 regression mới; toàn bộ 204 test PASS |
| **v0.36.0** | `89f94f8` | **Persistent providers & diagnostics**: trạng thái key đúng từng provider, một key/provider cùng tồn tại, model session lưu trước prompt, Save setting không reset model, HTTP/SSE error có chi tiết redact, provider 501 actionable. 8 regression mới; toàn bộ 212 test PASS |
| **v0.37.0** | `37e0bb6` | **Responsive shell & focused settings**: app shell gọn, sidebar/Workspace drawers, composer 5 modes, Connection cards, Theme, Settings theo role và fixed footer; guard async race, dedup model-save, validate Max tokens, keyboard/touch/focus. 8 regression mới; toàn bộ 220 test + Chromium 87/87 PASS |
| **v0.37.1** | main (release) | **Visible provider diagnostics**: giữ SSE error sau prompt, empty completion fail-closed thay vì lưu assistant null, read-only streaming diagnostic có redaction. 4 regression mới; toàn bộ 224 test + Chromium hotfix 1/1 PASS |
| **v0.38.0** | main (release) | **Bilingual Web UI**: Tiếng Việt/English trên login và Settings → Appearance, lưu theo thiết bị, labels/placeholders/errors/aria song ngữ; chat/batch/battle gửi language và demo theo ngôn ngữ; README + 3 ảnh English mới. 4 regression mới; toàn bộ 228 test + Chromium English 23/23 PASS |

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
| `auth.py` | SQLite users/browser sessions/Google identities/OAuth flows + registration policy; password/session chỉ hash, revoke/disable, dummy verify |
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
| **Web** (`server/` + `web/`) | Login/register email/password + Google có điều kiện, auth bootstrap trước data, cookie/CSRF wrapper, reset state khi đổi user, Team admin + signup toggle, model canonical theo session; responsive sidebar/Workspace drawers, composer 5 modes, Settings theo role + Theme + Tiếng Việt/English lưu theo thiết bị, keyboard/touch/focus; SSE chat/battle, terminal/files, diff, elicitation, ảnh 📎, fork/export/undo/nén/init |
| **TUI** (`tui/`) | Toàn màn hình textual: 3 panel (sessions/chat/files), Ctrl+M đổi mode, mọi lệnh slash, modal duyệt + elicitation |
| **CLI** (`cli/`) | REPL rich + `--once` + `--parallel` + `--battle` + `--profile`, mọi lệnh slash |
| **Demo mode** | Không cần key vẫn chạy tool thật (kịch bản mẫu) — người mới bật là chạy; reasoning/intro/final theo Tiếng Việt hoặc English đã chọn |

### 🌐 Server API (nhóm chính)
`/api/health` · `/api/auth/{me,register,login,logout,users,password,registration/*,google/*}` · `/api/settings` (GET/POST: key, model, mode, web_search, allow/deny, max_tokens) · `/api/keycheck` · `/api/models` (canonical multi-provider; live OpenRouter + Gemini direct) · `/api/sessions` CRUD · `/api/sessions/{sid}/model` (PATCH, owner + CSRF) · `/api/sessions/{sid}/chat` (SSE) · `/undo` `/compact` `/init` `/fork` `/export` · `/api/batch` · `/api/battle` (SSE) · `/api/approvals/{aid}` · `/api/elicitations` + `/api/elicitation/{eid}` · `/api/workspace/{exec,open,close,tree,file,upload,export}` · `/api/mcp` CRUD

---

## 3. Kiểm thử (release gate)

| Gate | Phạm vi | Kết quả |
|---|---|:-:|
| Full clean regression | 35 suite `scripts/test_*.py`, gồm security + TUI + v0.38 bilingual UI/demo | **228/228 PASS** ✅ |
| `scripts/test_v033.py` | Secret store/hash, 3 providers, sanitized subprocess env, API redaction, cookie login/public health, release lock, CORS/preflight, rate-limit, terminal setup | **12/12** ✅ |
| `scripts/test_v034.py` | AuthStore, anonymous/CSRF, email login/logout, Team, owner ACL, audit/usage/inbox/approval/elicitation, migration, registry/routing, concurrent providers, background owner, OIDC + RS256/JWKS local, image fail-closed, setup CLI/Web bundle, provider-specific demo/cost, member MCP/skills, first-run launcher | **17/17** ✅ |
| `scripts/test_v035.py` | Bootstrap guard, admin-only policy, signup disabled/CSRF, validation/member-only/auto-login/duplicate/role injection, toggle/disable, IP+email rate-limit, Google policy, production bundle, owner isolation giữa hai public member | **8/8** ✅ |
| `scripts/test_v036.py` | Ba provider key persist/reload + redaction, model session trước prompt + CSRF/owner ACL, Web-shaped chat vs image 501, provider 501 mock actionable, SSE error/done, concurrent routing, production bundle | **8/8** ✅ |
| `scripts/test_v037.py` | Version/clientInfo, responsive shell/drawers, synchronous session ref + async owner guards, model-save dedup, Settings/Theme/role tabs/fixed footer/validation, production bundle + persistent browser suite | **8/8** ✅ |
| `scripts/test_v0371.py` | Empty completion → error + không lưu null; completion bình thường vẫn lưu; Web chỉ reload timeline khi không có SSE error; diagnostic script + version | **4/4** ✅ |
| `scripts/browser_v037.cjs` chạy lại trên v0.38 | Responsive shell, Settings, validation, Theme, model request discipline, member, mobile drawers, late-response guard | **37/37 PASS** ✅ |
| `scripts/test_v038.py` | LanguageProvider/persistence; demo English chạy tool thật; default `vi` tương thích client cũ; Chat/Batch/Battle nhận và truyền language | **4/4** ✅ |
| HTTP smoke thật | v0.34 · Uvicorn :8765 + release mode + fake users/data tạm: cookie Secure/HttpOnly, CSRF, login/logout, SSE demo, Team/owner ACL, model theo session | **22/22 PASS** ✅ |
| Browser smoke thật | Fresh Chromium trên v0.37: audit key/model/empty-501/truncated-SSE **20/20** + responsive/Settings UX **37/37** + admin/member/model/ACL regression **14/14** + model-race **1/1** + signup **15/15** | **87/87 PASS** ✅ |
| Browser hotfix v0.37.1 | Fresh Chromium + production bundle: SSE 401 giả lập vẫn visible sau 1.5s, prompt được giữ, không runtime error | **1/1 PASS** ✅ |
| Browser English v0.38 | Login + localized auth errors, language switch/reload, admin/member tabs, validation, English demo + file thật, mobile drawers, không runtime error | **23/23 PASS** ✅ |
| README screenshots | `scripts/capture_readme_v038.cjs`: production English UI + demo giả; scan desktop Settings/agent và mobile không còn text tiếng Việt ngoài ý định | **PASS** ✅ |
| Responsive matrix | 320×720, 390×844, 768×900, 1024×768, 1440×1000; app + Settings/footer, không horizontal overflow/runtime error; mobile sidebar + Workspace drawer đã chụp/đọc | **PASS** ✅ |
| Static checks | mypy `server/` + `engine/`; TypeScript noEmit; Vite production build 43 modules | **PASS** ✅ |
| Security lint | bandit Medium+ trên engine/server/setup/migration/launcher | **0 finding** ✅ |
| Ruff | Full cho new files; changed-core gate ngoại trừ legacy `E402/BLE001/S110/S112/RUF100/RUF012`; không tuyên bố toàn repo sạch | **PASS theo phạm vi** ✅ |

Bundle cuối: `server/static/assets/index-ClsnKDFI.js` (251.12 kB) + `index-Dy17wNdU.css` (57.81 kB); Vite 43 modules.

Bug Phase 1 bị test bắt và đã sửa: demo dùng active provider global thay vì provider của model; battle dùng chung một demo boolean; background sub-agent mất router/owner default; architect đổi semantics TUI; demo bỏ ảnh vẫn đòi vision; `ScopedSessionStore` thiếu `allow_mcp`; launcher thiếu Authlib và còn kiểm tra shared release password. Các failure do fixture response shape/logout 204 được sửa ở test/smoke client, không nới product ACL.

Bug v0.36 bị repro bắt: Settings dùng mask của active provider cho mọi provider; đổi provider có thể mang draft key sang Save nhầm; model session chỉ ghi khi chat; Save setting khác reset model về default; empty/non-JSON HTTP error chỉ còn status; SSE cụt được coi là thành công; synthetic command thiếu `done`. Controlled test trên v0.35 tái hiện banner trần `HTTP 501` bằng response 501 body rỗng; v0.36 giữ status + endpoint + diagnostic. Provider 501 cũng được mock riêng để kiểm redaction và hướng xử lý tools/streaming/reasoning.

Bug v0.37 bị repro bắt: Workspace ở laptop chỉ còn khoảng 1px khi đóng; nút ☰ mobile không đóng được sidebar; nhập Max tokens `100` đóng dialog nhưng server vẫn giữ `4096`; member mở Settings thấy các global controls nhưng không thể Save. Bản vá dùng drawer/scrim/Escape và explicit grid columns, validation + focus tại field lỗi, member tabs theo capability (Giao diện/Skills/Audit) mà không nới server ACL. Các guard mới giữ response session/tree/context/PATCH đến muộn khỏi phiên hoặc user mới; blur model không đổi không PATCH. Fresh Chromium kiểm cả delayed GET/PATCH, touch delete, keyboard/focus, Theme và member flow.

Hotfix v0.37.1 từ incident Windows: OpenRouter diagnostic thật trả `401 Missing Authentication header`; UI lại im lặng vì SSE `error` bị `loadSession()` thay bằng persisted timeline ngay sau stream. v0.37.1 bỏ reload khi có SSE error, giữ prompt + cảnh báo. Mock empty stream cũng tái hiện `assistant_message: null`; Agent mới raise lỗi có model/finish_reason và không lưu assistant rỗng. Completion `OK` đối chứng vẫn stream/lưu đúng. `diagnose_llm.py` dùng synthetic prompt, không tools/session writes, redact credential và chỉ in response tối đa 6.000 ký tự. Bản vá cải thiện chẩn đoán nhưng **không tự sửa credential bị provider từ chối**.

v0.38 bổ sung English mà không bỏ tiếng Việt: `LanguageProvider` mặc định `vi`, lưu `forge-language`, cập nhật `<html lang>`; login có VI/EN và Appearance có selector. Chuỗi UI, placeholder, aria/title, confirmation và auth errors được song ngữ hoá. Chat/batch/battle gửi `language`; request cũ không có field vẫn mặc định `vi`. Demo đổi reasoning/intro/final nhưng vẫn chạy tool thật; phản hồi provider thật không bị ép dịch. Browser scan bắt và đã sửa các chuỗi sót `# ghi chú`, `/skills new <tên>`, `data/audit/<ngày>.jsonl`; 3 ảnh README được chụp lại từ production English UI với tài khoản/workspace giả.

**Chưa kiểm chứng:** Docker/container smoke (sandbox không có Docker CLI), Google OAuth thật bằng client production, và **nguồn HTTP 501 cụ thể trên máy Windows của user**. Empty-501 browser test và provider-501 mock kiểm cách hiển thị/xử lý, không chứng minh đó là nguồn ngoài máy user; cần banner chi tiết mới hoặc dòng log request để kết luận. OIDC đã kiểm bằng flow giả + JWT RS256/JWKS local; không dùng credential thật trong regression.

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
| [`README.md`](../../README.md) | Toàn bộ tính năng 3 giao diện + bảng v0.7/v0.8/v0.9 + hướng dẫn + bảo mật |
| [`QUICKSTART.md`](../guides/QUICKSTART.md) | 5 phút chạy lần đầu (dành người mới, Windows) |
| `FEATURE_AUDIT.md` | Ma trận 34 hạng mục vs 3 đối thủ + cập nhật từng phiên bản |
| `PRODUCT_DIRECTION.md` | Kim chỉ nam sản phẩm (research đối thủ 2026) |
| [`BUILD_DESKTOP.md`](../guides/BUILD_DESKTOP.md) / [`DEPLOY.md`](../guides/DEPLOY.md) | Đóng gói .exe / deploy server |
| [`SECURITY.md`](../guides/SECURITY.md) | Account/signup threat model, owner ACL, cookie/CSRF, OIDC, abuse controls, provider/MCP boundary, migration/rotation và checklist |
| `scripts/demo_mcp_server.py` | MCP server mẫu (4 tools, có elicitation thật để thử) |

## 6. Trạng thái bàn giao

- **Release:** v0.38.0, Web production build sẵn; ZIP `forge-agent-v0.38.0.zip`; v0.37.1 và artifact cũ giữ nguyên.
- **Git:** nhánh main, release v0.38.0 tạo từ working tree đã kiểm; v0.37.1 `42a5c52`, v0.37.0 `37e0bb6` và các tag/ZIP cũ giữ nguyên.
- **Kiểm thử:** 228/228 test · 35 suite · Chromium UX 37/37 + English 23/23 + hotfix 1/1 · responsive matrix 5 viewport ở baseline · mypy 0 lỗi / 39 files · bandit Medium+ 0.
- **Preview smoke:** uvicorn :8766, health 0.38.0, data/tài khoản giả; Google OAuth chưa cấu hình và không có provider credential thật.
- **Yêu cầu hệ thống:** Python 3.10+ · dependencies trong requirements (gồm Authlib) · OpenRouter/Google Gemini/custom provider hoặc demo không cần key.
- **Giới hạn đã ghi rõ:** single process/VPS; owner ACL không phải OS sandbox; public signup chưa có SMTP verification/CAPTCHA; chưa có image-generation adapter; real Google OAuth và Docker smoke còn lại.
