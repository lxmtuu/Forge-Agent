# 🧪 PROJECT_AUDIT — Rà soát toàn dự án theo chuẩn lập trình viên AI

> Ngày: 05/11/2026 · Commit sau audit: `b7049fd` (v0.17.1)
> **Phương pháp (không đoán):** ① Research khung chuẩn (OWASP Top 10 LLM 2025) → ② Đo bằng công cụ (ruff 0.17.3, bandit 1.9.4, coverage.py 7.17.2) → ③ Đọc code tại từng vị trí bị flag để xác nhận nguyên nhân gốc → ④ Sửa theo mức ưu tiên → ⑤ Chạy lại toàn bộ + thêm test hồi quy cho từng fix.

---

## 1. Nguyên tắc áp dụng (từ OWASP Top 10 cho LLM/Agent 2025)

| Mục OWASP | Ý nghĩa | forge-agent đạt nhờ | Trạng thái |
|---|---|---|---|
| **LLM01** Prompt Injection | Nội dung ngoài (email/web/skill) điều khiển model | Skills **trust gating** (v0.16), fetch_url chặn SSRF, approval gate | ✅ |
| **LLM02** Rò rỉ thông tin nhạy cảm | Token/PII lộ vào model/log | Provider key `data/provider-secrets.json` + connector token `data/secrets.json` (0600); **mask/redact**, subprocess sanitized (v0.33); token không vào system prompt (audit bằng grep: `agent.py` chỉ dùng key cho demo-check) | ✅ |
| **LLM05** Xử lý output thiếu kiểm soát | Output LLM chảy thẳng vào hệ thống thực thi | `guard.assess_command` chặn danger + **approval** cho warn (vẫn qua khi LLM "nghịch") | ✅ |
| **LLM06** Quá nhiều quyền/tự chủ *(rủi ro lớn nhất với agent)* | Agent làm việc thật không ai duyệt | Tool MCP chưa allowlist → **phải duyệt** (v0.17.0); `auto (YOLO)` là opt-in rõ ràng | ✅ |
| **LLM07** Lộ system prompt | Prompt chứa bí mật/logic mật | Prompt KHÔNG chứa secret (đã grep kiểm chứng) — prompt luôn coi như công khai | ✅ |
| **LLM10** Tiêu thụ không giới hạn | DoS / đốt tiền | Cap tool: buffer 60KB, fetch 20KB, todo 50 mục, skill ≤200, MCP CALL_TIMEOUT; **cost.py** hiển thị $ mỗi lượt | ✅ |

**Còn thiếu (ghi nhận, chưa làm):** audit log mọi tool call ra file (khuyến nghị OWASP), kiểm thử prompt-injection tự động (adversarial suite) — đưa vào backlog P2.
> ⚠️ **Đối chiếu 05/11 (tổng-kiểm tài liệu):** mục *audit log* ở dòng trên đã **ĐÓNG** (v0.17 log JSONL + v0.18 GET /api/audit + tab 📘, mask token). Số tổng test các vòng 9–15 đã **đếm lại theo per-suite** — mốc v0.33 **179 test / 29 suite**; v0.34 có **196 test / 30 suite**; v0.35 có **204 test / 31 suite**; v0.36 **212 test / 32 suite**; v0.37.1 **224 test / 34 suite**; v0.38.0 hiện hành **228 test / 35 suite** (các vòng ≤8 là số ghi tại thời điểm đó, suite tăng test theo vòng nên không phát sinh lại được). A4/A5/C1 đã **ĐÓNG v0.32** — GAP_ANALYSIS §2b không còn backlog; shared-server security đóng ở v0.33 (§3j).

## 2. Phát hiện bằng công cụ + đã xử lý

| # | Mức | Phát hiện | Nguyên nhân gốc (đã đọc code xác nhận) | Xử lý |
|---|---|---|---|---|
| 1 | 🔴 **P0 — crash** | `F823` cli/main.py:263 — **CLI interactive CRASH khi mở** (`UnboundLocalError: Text`) | v0.15 thêm local `from rich.text import Text` trong handler /skills nằm **cùng hàm** `interactive()` → Python coi `Text` là biến local toàn hàm → dòng banner (263) chạy trước import local | Xoá local import (module-level đã có); **chứng minh runtime: CLI boot đầy đủ**; thêm test hồi quy T2 |
| 2 | 🟠 P0 — an toàn | `tui/launch.py` bind **0.0.0.0** mặc định | Agent có tool chạy lệnh → exposing ra LAN là rủi ro OWASP LLM06 | Mặc định **127.0.0.1**, thêm `--host` khi cần chia sẻ |
| 3 | 🟠 P1 — hiệu năng | `/skills add` chạy `git clone` (tới 90s) **blocking event loop** server → mọi SSE/phiên khác đứng hình | `subprocess.run` trong async handler | `await asyncio.to_thread(skillmgr.add, …)` + test T5 |
| 4 | 🟡 P2 | Bandit `B324` MD5 (checkpoints.py) | Hash key nội bộ, không phải bảo mật — nhưng chuẩn hoá luôn | `usedforsecurity=False` |
| 5 | 🟡 P2 | `B904` ×2 (raise không `from`), `E741` ×2 (biến `l`), 13 lỗi lint scripts, import thừa (LLMError, `.lsp`) | Tích tụ qua các vòng | Dọn sạch; **bandit: 0 findings medium+** |
| 6 | 🟢 | Typo "Tổng kêeh" (memory.py — nghi vấn từ v0.12) | — | **Xác nhận có thật → sửa** "Tổng quan" |
| 7 | ✅ ĐÃ KIỂM — không sao | `atfiles` regex trên diff | Đã có **chặn path traversal** (`relative_to`) + cap số file/bytes; file phải tồn tại trong workspace | Ghi nhận rủi ro THẤP, chấp nhận |
| 8 | ✅ ĐÃ KIỂM — không sao | `B008` (`File(...)` default) | Là **idiom chuẩn FastAPI** cho UploadFile | Chấp nhận (false positive) |
| 9 | ✅ ĐÃ KIỂM — không sao | ASYNC240 (path ops trong async ở lsp/review) | File nhỏ, không hot-loop | Chấp nhận, ghi nhận backlog |
| 10 | ✅ Windows | asyncio subprocess (Proactor mặc định 3.8+), chmod bọc try, pathlib toàn bộ | — | Tương thích, không sửa |

## 3. Kiểm thử — số liệu thực đo

- **90/90 test xanh** trên **12 suite** (16+12+8+9+5+5+7+5+6+6+6+5) — mọi suite chạy lại sau từng fix.
- **Coverage (coverage.py, đo trên 12 suite):**

| Module | Trước audit | Sau audit | Ghi chú |
|---|---|---|---|
| server/main.py | 56% | **73%** | +test_v018 quét 20+ endpoint (settings, keycheck, usage, models, sessions CRUD, undo/compact/init/fork/export, approvals, elicitations, workspace CRUD/upload/zip, path-traversal 400) |
| connectors.py | — | 91% | (mới viết v0.17, test kèm theo) |
| guard.py | 92% | 92% | đạt |
| agent.py | 78% | 78% | vòng lặp + approval đã phủ; phần thiếu: battle/batch |
| tools.py | 78% | 78% | phần thiếu: lsp tools chi tiết |
| engine/llm.py | 38% | 40% | phần thiếu: đường mạng thật (hard) — cần fault-injection test |
| tui/app.py | 14% | 14% | ⚠ khoảng trống lớn nhất — cần textual harness (backlog P2) |
| **Tổng** | 67% | 63%* | *% tổng giảm do số dòng code tăng (+491 stmts) sau 3 vòng tính năng; các module lõi đều tăng/tanı đạt |

- Quy tắc mới áp dụng cho vòng sau: **mỗi fix bắt buộc kèm test hồi quy** (test_v018 T2–T5 đã làm mẫu).

## 3b. Vòng 2 (v0.17.2) — triển khai backlog P2 đúng nguyên tắc

| # | Mục | Kết quả thực đo |
|---|---|---|
| **A1** | **Audit log tool calls** (OWASP audit trail) | `engine/auditlog.py` — JSONL `data/audit/<ngày>.jsonl`, xoay theo ngày; **8 điểm ghi** trong agent.py (internal/MCP/hook-blocked/2 deny/3 spawn); **scrub token 2 lớp** (prefix `ghp_…`/`sk-…` + nhãn `Bearer|token|key[:=]`) — test xác nhận `sk-or-v1-SUPERSECRET99` KHÔNG lọt log; lệnh `/audit [n]` đồng bộ 3 UI |
| **A2** | **TUI smoke harness** (Textual Pilot headless) | `test_tui.py` 6 test: boot, /help, /skills, /audit, /connectors qua ô nhập THẬT + gửi tin chạy `run_turn` THẬT (key giả + LLM stub). **tui/app.py coverage 14% → 44%** |
| **A3** | **Adversarial security suite** | `test_security.py` 6 test: guard chống 21 payload bypass (chain `;&&||`, backtick, `$()`, newline, `${IFS}`, `--recursive`, hoa/thường) · approval (id khó đoán, double-resolve, timeout tự deny) · skill-chưa-trust chứa payload KHÔNG vào prompt · audit scrub · E2E audit entry |

### Bài học & phát hiện vòng 2 (đo đếm, không đoán)
1. **Bug thật #1 — auditlog nuốt log im lặng**: `(Path / "file".open(...))` — ưu tiên toán tử khiến `.open` gọi trên **chuỗi** → mọi log bịexcept nuốt. Test bắt được ngay, đã sửa (tách biến path).
2. **Bug thật #2 — quit giữa lượt làm TUI crash**: worker `finally` gọi `refresh_sessions` khi app đang shutdown (widgets đã gỡ) → `WorkerFailed: NoMatches('#sessions')`. Xác định bằng instrumentation `query_one` in stack — **không phỏng đoán**. Đã bọc try/except trong finally.
3. **Sửa guard theo kỹ thuật bypass đã research**: `${IFS}`/`$IFS` expansion + `rm --recursive/--no-preserve-root` từng là BYPASS — giờ là test hồi quy (và trước khi vá, test chạy THẤT đúng như kỳ vọng → chứng minh test có giá trị).
4. **Sai lầm được sửa trung thực**: đoán `run_turn` không chạy và "vá" bằng `asyncio.create_task` — test T7 văng `TypeError: a coroutine was expected, got Worker` → hóa ra `run_turn` có decorator **`@work(exclusive=True)`** (gọi là tự chạy Worker) — code gốc ĐÚNG, đã revert và viết lại test theo hành vi thật. Bài học: instrumentation trước, vá sau.

**Kết quả vòng 2: 102/102 test xanh (14 suite) · bandit 0 findings · TUI coverage 14%→44% · guard 95% · auditlog 86%.**

## 3c. Vòng 3 (v0.18) — P3 closeout

| # | Mục | Kết quả thực đo |
|---|---|---|
| **W1** | **Bảng Audit trong web** | `GET /api/audit?n=` (cap 1..500) + tab **📘 Audit** trong ⚙ Cài đặt: bảng ts/tool/source/ms/args, ô lọc realtime (tool/nguồn/đối số/note), nạp lại; test xác nhận token KHÔNG lọt qua endpoint |
| **W2** | **ASYNC240 → to_thread** | 3 chỗ blocking path ops (lsp.py ×2, review.py ×1) → ruff ASYNC240 giờ **0 findings**; hồi quy review/checkpoint chạy đúng |
| **W3** | **mypy baseline** | mypy 2.4.1: **6 module mới nhất (mcp/auditlog/connectors/skills/skillmgr/cost/background) SẠCH 100%** (fix annotation `dict[str, McpServer \| McpHttpServer]`); toàn engine/ = **75 lỗi/4 file — mốc baseline P3**, quy tắc: module sửa tới đâu sạch tới đó, module mới bắt buộc sạch |

**Kết quả vòng 3: 105/105 test (15 suite) · ruff F/E7/E9/B/ASYNC chỉ còn 3 mục đã-chấp-nhận-ghi-rõ · bandit 0.**

## 3d. Vòng 4 (v0.20) — Connectors P1: OAuth 2.1 + tab Dịch vụ

| # | Mục | Kết quả thực đo |
|---|---|---|
| **C6** | **OAuth 2.1 (engine/oauth.py)** | authorization-code + PKCE S256 (test vector RFC 7636 App.B) · loopback 127.0.0.1 (port ngẫu nhiên hoặc ghim theo preset — RFC 8252 §7.3) · state chống CSRF (sai state = TỪ CHỐI, không gọi token endpoint — test chứng minh) · DCR RFC 7591 khi có registration_endpoint · Basic/post auth-style (Notion=Basic) · refresh ngầm khi hết hạn · token lưu secrets.json chmod 600, chỉ mask khi hiển thị |
| **C7** | **Tab "🔗 Dịch vụ" trong ⚙ Cài đặt** | GET /api/connectors/presets · POST …/oauth/start (chạy nền thread) · GET …/oauth/status (poll) · DELETE …/oauth; nhập client_id/secret ngay trong tab, nút Kết nối → chờ duyệt browser |
| Presets | notion + sentry → `oauth` thật (loopback_port 8765), linear thêm oauth tuỳ chọn; supabase qua hub | CLI `/connectors oauth\|logout` · TUI chạy trong worker thread (không khoá UI) |

**Bài học vòng 4:** (1) `Loopback` thiếu `serve_forever()` — socket bind nhưng không accept, test E2E bắt được; (2) bump version bằng sed khớp chuỗi cũ đã TRƯỢT qua 2 vòng (zip 0.18/0.19 mang metadata 0.17) — từ nay: bump xong luôn `grep -n version pyproject.toml engine/lsp.py` xác nhận; (3) bandit B107 nhặt đúng mặc định `client_secret=""` → chuyển `None`.

**Kết quả vòng 4: 116/116 test (17 suite) · bandit Medium+ = 0 · ruff module mới sạch.**

## 3e. Vòng 5 (v0.21) — Kiến trúc sư & Chỉnh lại

| # | Mục | Kết quả thực đo |
|---|---|---|
| **A6** | **Architect 2-model** | mode `architect`: giai đoạn PLAN gọi `resolve_model("strong")` KHÔNG tool (prompt ép chỉ lập kế hoạch ~200 từ) → sự kiện `phase plan/execute` stream riêng → giai đoạn EXECUTE gọi `resolve_model("cheap")` đủ TOOL_SPECS với prompt "thực hiện ngay, không hỏi lại"; kế hoạch lưu vào session như assistant msg — test stub chứng minh đúng model/tool/prompt từng pha |
| **E5** | **Sửa tin & chạy lại** | `POST /api/sessions/{sid}/rerun {index,text}` cắt session từ tin user + thay nội dung (400 nếu index sai/không phải user, 404 nếu lạ) → web: ✏️ trên bubble (hover), hộp sửa Enter=chạy lại/Esc=huỷ, cắt timeline rồi `/chat rerun=true` → `agent.send(append_user=False)` KHÔNG append trùng (test chứng minh) |
| **C5** | **Hub UX web** | tab 🔗 Dịch vụ: nút **＋ Cài** / **🗑 Gỡ** preset trực tiếp (`POST /api/connectors/install?id=`, `DELETE …/installed`) — không còn bắt gõ CLI |

**Kết quả vòng 5: 120/120 test (18 suite) · bandit Medium+ 0 · tsc sạch · ruff các dòng sửa sạch (phần never-raise cũ giữ làm baseline có ghi chú).**

## 3f. Vòng 6 (v0.22) — Auto-commit & Effort

| # | Mục | Kết quả thực đo |
|---|---|---|
| **B1 (P0!)** | **Auto-commit (opt-in)** | `engine/autocommit.py`: git init ngầm + định danh bot cục bộ → sau lượt agent có thay đổi → commit Conventional Commits do model `cheap` sinh từ `diff --stat` + ngữ cảnh (stub test xác nhận nhận đúng prompt); LLM lỗi → fallback heuristic vẫn đúng format; không đổi gì → không commit; trailer "🤖 forge-agent" để lọc. Bật/tắt: ⚙ An toàn (web) · `/autocommit on\|off` (CLI/TUI) · `/commit` thủ công |
| **D3** | **Reasoning effort** | setting low/medium/high → payload `"reasoning": {"effort": …}` — **chỉ gửi qua OpenRouter** (server OpenAI-compat lạ có thể từ chối field lạ — thiết kế an toàn, test (c) chứng minh); validate giá trị sai → về mặc định |

**Bài học vòng 6:** test D3 lần đầu đặt `custom_base_url` về fake-server để chặn traffic → tự tắt chính tính năng đang test (đúng thiết kế!) và một request đi thẳng ra OpenRouter thật (401). Bài học: **khi test thứ gắn chặt với 1 nhà cung cấp, giả mạo điểm chọn-endpoint (`_endpoint`), không phải base_url.**

**Kết quả vòng 6: 125/125 test (19 suite) · bandit Medium+ 0 · ruff module mới sạch.**

## 3g. Vòng 7 (v0.23) — Nhịp lặp & Xuất audit

| # | Mục | Kết quả thực đo |
|---|---|---|
| **F1** | **/loop — lịch định kỳ** | `engine/scheduler.py`: parse_interval (45s/30m/2h/1d/số=phút, clamp 10s..7d) + LoopManager (1 phiên 1 loop; max_runs tự dừng; lượt hỏng không chết loop). Server: POST/GET/DELETE `/api/sessions/{sid}/loop` — mỗi nhịp chạy ĐỦ lượt agent (tool + audit + session persist, web tải lại là thấy). CLI: asyncio task. TUI: `set_interval` (nhịp bỏ qua nếu đang busy). Lệnh `/loop`, `/loop off` đủ 3 UI (web qua chat `/loop`) |
| **P3** | **Xuất audit CSV** | `GET /api/audit/export` (csv chuẩn, escape đúng giá trị có dấu phẩy — test parse ngược bằng csv.reader) + nút ⤓ trong tab Audit |

**Bài học vòng 7:** (1) loop hoàn tất tự nhiên mà pop entry → status mất thống kê `runs/last_ok` — test bắt được; giữ entry finished làm báo cáo; (2) dùng lại pattern test chat cho shape API mà không đọc route → KeyError `message_count` (endpoint trả `messages`) — lại là bài học "đọc handler trước khi viết test".

**Kết quả vòng 7: 129/129 test (20 suite) · bandit Medium+ 0 · ruff module mới sạch.**

## 3h. Vòng 8 (v0.24) — Worktree isolation

| # | Mục | Kết quả thực đo |
|---|---|---|
| **B2** | **Sub-agent `isolation=worktree`** | `engine/worktree.py`: `make()` tạo `wt-<sub>` từ branch `iso/<sub>` rẽ nhánh tại `forge` (repo checkpoint của cha) → sub làm việc trong bản sao (sửa/thêm/XOÁ đều không đụng workspace cha — test chứng minh) → `diff_stat` theo điểm rẽ nhánh → `merge` (patch `--binary` áp bằng `git apply -C <ws-cha>`) hoặc `discard` (dọn wt + branch + repo). Lệnh `/worktree list\|merge\|discard` đủ 3 UI + REST. Không có checkpoint → tự fallback chia sẻ (an toàn hơn fail) |
| B2-fork | **Fork từ snapshot** | fork xuất cây bằng `git archive forge` (nhanh, trạng thái nhất quán — test: file đổi SAU snapshot không lọt vào fork); không có checkpoint → copytree như cũ |

**Bài học vòng 8 (quan trọng nhất từ trước tới nay):** khi chèn method mới vào tui/app.py, tôi neo edit vào dòng `async def run_turn` và **làm rơi decorator `@work(exclusive=True)`** (đính nhầm lên method mới) → `run_turn` thành coroutine không ai await → **TUI không chạy lượt nào** (RuntimeWarning "coroutine never awaited"). Chỉ nhờ test hồi quy T7 (gửi tin thật qua ô nhập) bắt được. Quy tắc mới: **(1) edit anchor phải bao gồm cả dòng decorator/context phía trên; (2) sau mọi sửa TUI phải chạy `scripts.test_tui`; (3) cảnh báo "never awaited" = decorator @work mất — kiểm tra ngay.** Thêm 2 bài học nhỏ: `git archive/diff --binary` phải đi qua pipe BYTES (decode text làm hỏng tar/patch — 2 lần dính); `git apply` không tôn trọng `--work-tree` (phải `git -C <dir> apply`).

**Kết quả vòng 8: 129/129 test (21 suite) · bandit Medium+ 0 · ruff module mới sạch.**

## 3i. Vòng 9 (v0.25) — Liên phiên & Ký năng rõ phép

| # | Mục | Kết quả thực đo |
|---|---|---|
| **F2** | **Cross-session messaging** | `engine/bus.py`: JSONL `data/messages/<sid>.jsonl` + mốc đọc theo offset (`<sid>.read`); tool **send_message** (validate phiên tồn tại, chặn self-send) + **check_inbox** (đọc = mark-read); đầu lượt có tin chưa đọc → system prompt nhắc "INBOX: N tin — gọi check_inbox" (test chứng minh có/hết tin); REST POST/GET (peek=true không đổi mốc); `/msg <phiên> <nội dung>` + `/inbox` đủ 3 UI. Hợp lực: gửi chỉ đạo cho phiên `/loop` đang nền |
| **S7** | **allowed-tools hiển thị** | /skills listing hiện `🔑 read_file, list_dir…` cho skill khai báo allowed-tools (chỉ hiển thị — experimental, đúng kế hoạch SKILLS_RESEARCH) |

**Bài học vòng 9:** chèn 2 tool specs vào TOOLS_LIST — chèn đúng vị trí tên nhưng SAI mức lồng (thiếu wrapper `{"type": "function", "function": {…}}` giữa 2 entry) → SyntaxError. py_compile bắt ngay; sửa bằng edit_file từng khớp nối. Quy tắc nhắc lại: **với cấu trúc lồng nhau (list[dict]), mọi chèn giữa phải kèm cả wrapper đóng/mở.**

**Kết quả vòng 9: 139/139 test (22 suite) · bandit Medium+ 0 · ruff module mới sạch.**

## 3j. Vòng 10 (v0.26) — Skills trong web

| # | Mục | Kết quả thực đo |
|---|---|---|
| **S8** | **Tab 🧩 Skills trong ⚙ Cài đặt** | GET `/api/skills?sid=` (catalog + diagnostics) · POST `/api/skills/toggle` (bật/tắt model-invocation bằng frontmatter surgery — sửa/thêm/xoá `disable-model-invocation`, file legacy không frontmatter → tự tạo **đầy đủ name+description**) · POST `/api/skills/trust`; tab hiển thị nhóm nguồn, badge 🔒/🔕/⚠, nút Cấm/Cho model gọi + Tin skill |

**Bài học vòng 10 (2 lớp):** frontmatter tối thiểu khi tự tạo phải ĐỦ `name` **và** `description` — thiếu name → parse lệch; thiếu description → spec BỎ skill ("thiếu description → BỎ") khiến skill biến mất khỏi catalog. Test T2 bắt cả 2 lớp qua StopIteration → diagnostic in catalog/diags mới thấy nguyên nhân thật.

**Kết quả vòng 10: 143/143 test (23 suite) · bandit Medium+ 0 · ruff module mới sạch.**

## 3k. Vòng 11 (v0.27) — mypy về 0

| Mục | Kết quả thực đo |
|---|---|
| **mypy engine/ = 0 lỗi (32 file)** | Đo lại thấy baseline TRƯỢT XUỐNG 96 lỗi/7 file (v0.22–0.26 thêm autocommit/worktree/oauth nhưng chưa chạy mypy — vi phạm đúng quy tắc nhà). Sửa triệt để: (1) **narrow 1 chỗ ở nguồn** — `Agent.__init__` gán `self.session: Session = s0` sau raise → tắt 61/76 lỗi của agent.py; (2) pattern `GIT: str \| None` → gán biến cục bộ narrow trước `create_subprocess_exec` (checkpoints ×2, worktree); (3) `proc.returncode or 0` (returncode là `int \| None`); (4) tách biến list/str tái dùng trong autocommit (mypy bắt đúng chỗ code khó đọc); (5) `bool(result["ok"])` 2 chỗ log_tool; (6) sửa 1 bug tools.py thật: **ghi vào `proc.returncode` (property read-only) — thay bằng biến `hook_rc`**. Config chuẩn hoá `[tool.mypy]` trong pyproject.toml → `python -m mypy engine/` không cần flag |

**Kết quả vòng 11: 143/143 test (23 suite) · mypy 0 · bandit Medium+ 0 — 3 gate đều xanh.**

## 3l. Vòng 12 (v0.28) — Rà soát 6 gói MCP theo yêu cầu

Yêu cầu: kiểm tra đã có **MCP Playwright · File System · Postgres · Github · Context7 · Sequential Thinking** chưa — kiểm tra bằng code + research chuẩn trước khi sửa.

| Gói | Trước | Sau |
|---|---|---|
| MCP Playwright | ✅ có sẵn (stdio npx, E2E thật: **25 tools**) | giữ — E2E xác nhận |
| Context7 | ✅ có sẵn (HTTP remote, E2E thật: 2 tools resolve-library-id/query-docs) | giữ — E2E xác nhận |
| Sequential Thinking | ❌ | **thêm preset** stdio npx @modelcontextprotocol/server-sequential-thinking — E2E thật: tool `sequentialthinking` vào specs |
| File System | ❌ | **thêm preset** stdio npx @modelcontextprotocol/server-filesystem, thư mục qua `$FORGE_FS_DIR` (cảnh báo: ghi ngoài workspace không có checkpoint/undo) |
| Postgres | chỉ có Supabase remote (OAuth org) | **thay bằng preset `postgres`** stdio npx @modelcontextprotocol/server-postgres qua `$DATABASE_URL` — CHỈ ĐỌC theo thiết kế server; E2E thiếu env → status `error` rõ ràng |
| Github | ✅ preset `github` (remote chính thức api.githubcopilot.com + PAT) | research: @modelcontextprotocol/server-github đã **deprecated** → KHÔNG thêm bản stdio trùng; ghi rõ ánh xạ |

**Khoảng hở thật được vá:** `mcp.py` KHÔNG resolve `$VAR` trong args → postgres/filesystem sẽ chết với chữ literal `$DATABASE_URL`. Đã thêm `McpManager._expand_args()` (biến đứng một mình thiếu → rỗng cho lỗi rõ; biến nhúng → expandvars) chạy lúc spawn — đổi env chỉ cần refresh.

**Bài học vòng 12:** (1) status "stopped"/error None khi xem TRƯỚC khi start — test phải đi đúng flow thật (get_tool_specs/refresh gọi start); (2) status hiển thị template `$VAR` nguyên bản là ĐÚNG (resolve lúc spawn), assert test phải tách bạch template vs lỗi.

**Kết quả vòng 12: 148/148 test (24 suite) · mypy 0 · bandit Medium+ 0 · ruff connectors/mcp sạch.**

## 3j. Vòng 13 (v0.29) — Research & mở rộng MCP catalog

Yêu cầu: "xem còn các MCP nào nữa" — research 3 hướng (PulseMCP/toplist landscape, remote chính thức Stripe/Atlassian/Vercel, gói stdio active vs archived) trước khi chọn.

**Thêm 7 preset (11 → 18):** stripe (`mcp.stripe.com`, Bearer Restricted Key — research: OAuth hoặc API key), atlassian (`mcp.atlassian.com/v2/mcp`), vercel (`mcp.vercel.com`), supabase remote (mặc định read_only), memory (npx chính thức, E2E thật: create_entities/search_nodes vào specs), fetch (uvx `mcp-server-fetch` — E2E skip khi máy thiếu uv), brave-search (**gói chính thức mới `@brave/brave-search-mcp-server`** — bản modelcontextprotocol đã archived).

**Cố tình KHÔNG thêm (ghi lý do trong MCP_CATALOG.md):** server-github/brave/slack stdio (archived upstream), git/time/everything (trùng/trivial), puppeteer/sqlite/redis/gdrive (archived hoặc OAuth service-account phức tạp — Google apps qua hub Composio).

**Bài học vòng 13:** (1) cùng một server có thể có vòng đời 2 đời — active tại modelcontextprotocol/servers vs servers-archived: PHẢI trỏ gói mới nhất (brave là ví dụ); (2) endpoint remote phải lấy từ docs nhà cung cấp/nguồn độc lập ≥2 — không đoán URL authorize/token nếu chưa thấy tài liệu (vercel/atlassian → oauth-pending + hub thay vì bịa endpoint).

**Kết quả vòng 13: 153/153 test (25 suite) · mypy 0 · bandit Medium+ 0 · ruff connectors/mcp sạch.**

## 3i. Vòng 14 (v0.30) — Audit UI v2 + sửa claim backlog stale

Yêu cầu chọn "Audit-log UI bảng (P3)". **Điều tra bằng git làm lộ sự thật: P3 đã ĐÓNG từ v0.18.0** (f60e42a — tab 📘 Audit: lọc realtime, refresh, CSV, mask token, 200 mục). Claim "còn P3" trong backlog là **stale** — đã sửa PROJECT_AUDIT. Thay vì bỏ trắng vòng, nâng cấp UI lên chuẩn log-viewer:

| Nâng cấp | Chi tiết |
|---|---|
| Quick-filter trạng thái | 3 chip **Tất cả / ✅ / ❌** — bắt lỗi nhanh mà không cần gõ |
| Cột phiên | hiển thị 6 ký tự cuối sid, hover thấy đầy đủ; filter text giờ quét cả session |
| Click dòng → chi tiết | expand: ts đầy đủ, phiên, nguồn, ghi chú, **args JSON pretty** (không cắt 90 ký tự như dòng chính) |
| Test chống quên build | test_v030-T3 assert build artifact trong server/static chứa `audit-chip/audit-detail/audit-sid` — sửa TSX mà quên `npm run build` sẽ đỏ ngay |

**Kết quả vòng 14: 157/157 test (26 suite) · mypy 0 · bandit Medium+ 0 · tsc/vite build ✓.**

## 3h. Vòng 15 (v0.31) — Onboarding: launcher 1-click + USER_GUIDE tiếng Việt

Hai mục "quà cho người dùng cuối" còn lại — làm cả hai. Research trước: (1) bat phải **pure-ASCII** vì cmd parse file theo codepage console TRƯỚC khi chcp trong file kịp chạy → chữ có dấu chuyển hết vào `scripts/launch.py` (Python tự reconfigure stdout UTF-8); (2) pattern onboarding đối thủ (Claude Code quickstart): install → verify → chạy → hướng dẫn xác thực lần đầu.

| Thành phần | Chi tiết |
|---|---|
| `run_forge.bat` | wrapper mỏng ASCII: tìm `py -3` → `python`; lỗi không có Python → hướng dẫn + pause; double-click chạy được |
| `scripts/launch.py` | logic thật: tạo `.venv` (lần đầu) → `pip install -e .` → chạy uvicorn → chờ cổng → mở browser; `--check` khám phá môi trường không khởi động; `FORGE_PORT` đổi cổng; cổng bận → mở luôn tab, không chạy bản thứ hai |
| `run_forge.sh` | macOS/Linux mỏng, exec launch.py |
| `USER_GUIDE.md` | 11 mục đánh số + phụ lục lệnh: yêu cầu → cài/chạy 2 bước → key OpenRouter → 3 chế độ → việc thường ngày → skills/subagents → 18 MCP → an toàn → sự cố (bảng) → cập nhật/gỡ |
| **Test chống bịa docs** | test_v031-T4: tách MỌI token `/slash` khỏi guide (đã strip URL) — mỗi token phải tồn tại trong source cli/tui/server/engine; T1 assert bat thuần ASCII + không chữ chcp |

**E2E thật của launcher (sandbox):** venv tạo thật → pip install thật → server :8010 lên thật → health ok · demo true → banner UTF-8 chuẩn.

**Kết quả vòng 15: 162/162 test (27 suite) · mypy 0 · bandit Medium+ 0.**

## 3i. Vòng 16 (v0.32) — Autonomy nâng cao: A4 + A5 + C1

Đúng quy trình research → đọc code/contract → implementation → test hồi quy. Research Claude Code background subagents (Notification `agent_completed` + tóm tắt về lead) và Aider RepoMap (symbol + rank tham chiếu + budget); không chép tree-sitter/PageRank nguyên bản vì mục tiêu là map gọn, dependency không đổi.

| Hạng mục | Implementation kiểm chứng |
|---|---|
| A4 sub-agent nền | Registry in-process, cap 3 running/lead, session/model riêng, shared/worktree; lead nhận summary qua bus + audit + Notification `agent_completed`; `check_background_agents` đọc trạng thái |
| A5 repo map | Module mới `repomap.py`: symbol regex py/js/ts/go/rs, rank refs chéo, budget, cache theo full path+mtime+size+budget; auto-nạp ≤60 file/≤4KB/không cắt; tool + `/repomap` CLI/TUI |
| C1 hook events | `run_event` dùng đúng contract `_run_cmd` `{code,out,err}`; prompt/pre_compact chặn bằng exit 2, stop/notification không chặn; bỏ hook nội bộ cho bg-child |

**Lỗi test bắt trước khi ship:** cache chéo workspace và thiếu budget trong key (T1) · thiếu import asyncio (T5) · sửa lint ISC004 sai làm hỏng 3 thông báo LSP (test_v011) · thêm test workspace rỗng + thay đổi file sau phần tử 200. Không “sửa test để qua”: mock LLM chỉ thay đường gọi mạng; vòng đời agent, hooks, bus và registry chạy thật.

**Kết quả vòng 16: 167/167 test (28 suite) · mypy 0/33 file · bandit Medium+ 0 · ruff sạch cho `repomap.py`/`tools.py`/`hooks.py`; `agent.py`/CLI/TUI không phát sinh lỗi lint mới so với baseline đã ghi nhận.**

## 3j. Vòng 17 (v0.33) — Shared-server security + terminal setup

Phạm vi chốt: một server dùng chung cho nhóm tin cậy, operator giữ key; không phải BYOK per-user và không giả lập multi-tenant isolation. Không đọc/migrate key thật trong regression — toàn bộ suite dùng fake key + `FORGE_DATA_DIR` tạm.

| Hạng mục | Implementation kiểm chứng |
|---|---|
| Subprocess secret boundary | `secrets.sanitized_env()` cho shell/hook/background/git/checkpoint/worktree/review/LSP/skill manager; AST scan cả env build từ `os.environ`; MCP chỉ nhận secret explicit trong `env` |
| Terminal + providers | `scripts/setup_keys.py` nhập ẩn, không `--key`; OpenRouter, Google Gemini OpenAI-compatible, custom; provider-aware demo/fallback/cost/keycheck/CLI/TUI/Web |
| Secret/auth store | `provider-secrets.json` tách khỏi config + migrate legacy; release password PBKDF2-HMAC-SHA256 240k + salt, file 0600 best-effort; data ngoài git/ZIP |
| Release middleware | Basic/Bearer auth toàn Web/API/static, thiếu auth 503, sai auth 401, Settings/keycheck 403; UI lock + setup hint |
| CORS + quota | Release same-origin mặc định, wildcard startup error, preflight explicit origin hoạt động; LLM/auth rate-limit 429 + Retry-After |
| Error/browser hygiene | Redact Authorization key khỏi provider error; health chỉ mask; Web không lưu credential vào browser storage |

**Lỗi thật test bắt trước ship:** checkpoint `snapshot/undo/list` còn nhánh `{**os.environ}` mà scan keyword-only đã bỏ sót; migration ghi legacy key đè key mới; tên mục doctor làm regression v0.10. Đều vá code và chạy lại, không hạ tiêu chí test.

**Kết quả vòng 17: 179/179 test (29 suite) · mypy 0/34 file · bandit Medium+ 0 · Web build PASS · ruff sạch cho `engine/secrets.py`, `scripts/setup_keys.py`, `scripts/test_v033.py`.** Không tuyên bố ruff toàn repo sạch; các lỗi baseline đã ghi nhận ở các vòng trước giữ nguyên phạm vi.


## 3k. Vòng 18 (v0.34) — Private team + multi-provider routing

Phạm vi Phase 1: một VPS/process, private team do admin mời, không public registration; provider key vẫn do operator giữ. Owner ACL ở application layer không được tuyên bố là OS sandbox hay isolation chống user độc hại.

| Hạng mục | Kết quả |
|---|---|
| Identity | `engine/auth.py` + `server/auth.py`: SQLite users/sessions/Google identities/OAuth flows, email/password + Google OIDC, cookie HttpOnly + CSRF, revoke/disable, giữ last admin, không Basic/shared password |
| OIDC | PKCE S256/state/nonce, RS256/JWKS, issuer/aud/exp/nonce/email_verified; chỉ `openid email profile`, không Gmail/offline scope |
| Owner ACL | Session/workspace/fork/export/batch/battle/sub-agent/loop/messages/worktree/audit/usage/inbox/approval/elicitation đều scoped; legacy owner rỗng bị ẩn |
| Model | Canonical `openrouter:vendor/model`, `google:gemini-...`, `custom:...`; model theo session, provider key chỉ lưu phía server; demo/cost/fallback/background route theo từng request |
| Member boundary | Không đổi global settings/Team/MCP/connectors/global skills; không nạp MCP credential toàn server; project workspace/skills vẫn dùng được |
| Web | Auth bootstrap trước data, login/logout/reset user state, Team/Google config, admin-only tabs, model selector theo session, provider của key tách default routing |
| Vận hành | `setup_auth.py`, `migrate_sessions.py` dry-run/`--apply`, launcher first-run bootstrap + Authlib dependency check, docs HTTPS/migration/rotation |
| Image | Capability contract tồn tại nhưng adapter chưa có; catalog báo `adapter=false`, request trả 501 |

**Release gate:** 196/196 test (30 suite), v0.34 17/17; HTTP smoke 22/22 và Playwright 14/14 với data/tài khoản giả; mypy server/main.py + engine/ · 38 files; TypeScript + Web build 42 modules; bandit Medium+ 0. Ruff full cho new files và changed-core gate theo phạm vi, không tuyên bố toàn repo sạch.

**Chưa kiểm chứng:** Docker CLI/container smoke và real Google OAuth. Không dùng credential thật trong test; OIDC fake flow/JWKS local không thay thế production consent/callback smoke.


## 3l. Vòng 19 (v0.35) — Opt-in public signup + auth UX

User yêu cầu mở self-registration sau khi preview v0.34 chỉ có invite-only. Thay đổi được tách thành release mới; tag/ZIP v0.34 không bị ghi đè.

| Hạng mục | Kết quả |
|---|---|
| Policy | Public signup mặc định tắt; admin bật/tắt trong Team. `FORGE_ALLOW_REGISTRATION` chỉ là default ban đầu, lựa chọn trong Auth DB được ưu tiên |
| Endpoint | `POST /api/auth/register`: CSRF, yêu cầu admin bootstrap, password ≥16 ký tự, email/name validation, duplicate 409, role injection 422, auto-login + CSRF rotation |
| Quyền | Payload public không nhận role/enabled; chỉ tạo member. Admin tắt signup không revoke user cũ; disable user vẫn revoke sessions |
| Abuse control | 5 lượt/15 phút/IP + 3 lượt/15 phút/email trong một process, `429 + Retry-After`; docs yêu cầu gateway quota/CAPTCHA khi public Internet |
| Google | Signup tắt = invite-only; signup mở = Google user mới chỉ tạo member. PKCE/state/nonce/RS256 và OIDC scopes không đổi |
| Web | Mục Đăng ký, form tên/email/password/xác nhận, validation, auto-login, trạng thái Google chưa cấu hình; admin có signup toggle |
| Giới hạn | Chưa có SMTP email verification hoặc CAPTCHA tích hợp; owner ACL vẫn không phải OS sandbox |

**Release gate:** 204/204 test (31 suite), v0.35 8/8; Chromium signup 15/15 + admin/member regression 14/14; mypy server/main.py + engine/ 38 files; TypeScript + Web build 42 modules; bandit Medium+ 0. Ruff theo scoped gate, không tuyên bố toàn repo sạch. Real Google OAuth và Docker/container smoke vẫn chưa chạy.

## 3m. Vòng 20 (v0.36) — Persistent provider keys/models + error diagnostics

User báo trên Windows/localhost v0.35: key dường như biến mất khi mở lại Settings, banner `HTTP 501` chặn prompt tiếp theo sau chuỗi background tools, và cần nhiều provider/model cùng được lưu. Audit tách riêng persistence thật, UI state và nguồn lỗi; không suy root cause từ screenshot.

| Hạng mục | Repro / kết quả |
|---|---|
| Key persistence | Trước vá, suite mới đã PASS phần lưu tuần tự OpenRouter → Google → Custom: cả ba secret tồn tại sau reload, blank Save không xoá, response/config không rò secret. Không có bằng chứng backend tự xoá key |
| Settings UX | Root cause hiển thị: mask chỉ thuộc active provider nhưng bị dùng cho mọi `keyProvider`; modal cũng mở lại theo active provider. v0.36 dùng `provider_keys[provider]`, overview cả ba trạng thái, nhớ provider đã chọn bằng preference không-secret, ô password trống có giải thích |
| Draft isolation | Đổi provider xoá draft key + keycheck để không lưu secret của A sang B. Browser test điền Google → Custom → Google xác nhận draft không đi qua provider khác |
| Multi-provider | Phạm vi là **một key cho mỗi provider**, cả ba cùng tồn tại; không phải key rotation/nhiều key cùng provider. Mock ba call đồng thờI đúng URL/model/Authorization, không mutate global provider |
| Model persistence | Trước vá `PATCH /api/sessions/{sid}/model` trả 405; model chỉ được Agent ghi khi chat. Endpoint mới canonicalize/validate, lưu ngay qua ScopedSessionStore + CSRF. Reload trước prompt giữ model; invalid không ghi đè; user khác 404. Response PATCH chậm của session A không được đè model UI của session B vừa chọn (browser race test) |
| Save semantics | Trước đây Settings luôn đẩy active model về default. v0.36 chỉ đổi session khi ô Model thật sự dirty; Save key/max tokens giữ model hiện tại. Đổi Model explicit lưu default + current session |
| HTTP 501 | Sole explicit internal 501 vẫn là `image_generation`; Web chat thường không gửi capability này. Web-shaped request trả SSE 200. Controlled Playwright trên v0.35 với empty 501 tái hiện đúng banner trần `HTTP 501`; v0.36 hiện status + endpoint + empty-body diagnostic, non-JSON/JSON detail đã redact |
| Provider 501 | Mock provider 501 cho thấy lỗi trong lượt Agent là SSE `error + done`, không phải pre-stream 501. Thông báo mới nêu tool calling/streaming/reasoning và model khác/Direct/tắt Effort để chẩn đoán; credential bị redact |
| SSE ẩn | Trước đây stream cụt không `done` được coi là thành công và exception của event callback nằm trong catch JSON. v0.36 tách parse/dispatch, báo stream kết thúc sớm; synthetic command được sửa để gửi `done`, tránh lỗi giả |
| Chưa kết luận | Chưa nhận response/log từ request 501 thật trên Windows nên **không tuyên bố đã xác định hoặc loại bỏ root cause ngoài máy user**. Query `google_state` chỉ là dấu hiệu OAuth cần xem thêm, không phải nguyên nhân chat đã chứng minh |

**Release gate:** 212/212 test (32 suite), v0.36 8/8; Chromium audit 20/20 + model-race 1/1 + signup 15/15 + admin/member regression 14/14 = 50/50; mypy `engine/` + `server/` 39 files; TypeScript + Web build 42 modules; bandit Medium+ 0. Ruff theo scoped gate. Real Google OAuth, Docker/container smoke và nguồn 501 ngoài máy Windows vẫn chưa kiểm chứng.

## 3n. Vòng 21 (v0.37) — Responsive shell + focused Settings

Đợt này redesign Web shell nhưng giữ nguyên owner ACL, CSRF, session revoke, provider secret boundary và release auth. Repro chạy trên production bundle bằng Chromium thật với data/tài khoản giả; không sửa assertion để che data bẩn và không suy đoán lỗi từ một screenshot đang animation.

| Hạng mục | Repro / kết quả |
|---|---|
| App shell | Gom mode/song song/model vào composer toolbar; top bar giữ tên/ID phiên và Workspace/Settings; empty state có ba prompt mẫu. Desktop 1440×1000 chat 852px/composer 186px; laptop 1024×768 chat 800px/composer 186px |
| Responsive drawers | Baseline bắt Workspace đóng còn khoảng 1px và ☰ mobile không đóng được. Bản vá có nút đóng, scrim, Escape, explicit grid column; mobile 390×844 chat 390px/composer 267px, Workspace drawer rộng 366.59px. Matrix 320/390/768/1024/1440 không horizontal overflow/runtime error |
| Touch + keyboard | Session, folder/file và delete không phụ thuộc hover; sidebar/Workspace có dialog semantics, focus trap/restore và nút close rõ ràng. Browser kiểm cả touch delete và Escape |
| Settings | Connection tách Provider & credentials / Model & generation; Custom URL chỉ hiện với Custom. Header/footer cố định, nội dung cuộn riêng, tab navigation cuộn được trên mobile, select theo theme |
| Member + Theme | Member chỉ thấy Giao diện/Skills/Audit; Theme Dark/Light/Amber áp dụng tức thì và lưu local theo thiết bị. Không mở global Settings Save hoặc nới ACL cho member |
| Validation | Repro Max tokens `100`: trước vá dialog đóng nhưng server giữ `4096`; sau vá invalid không POST, dialog mở và focus field lỗi. Fresh-run lưu `16384 → 4096` rồi khôi phục |
| Async ownership | `sidRef` synchronous + per-user/owner guards giữ delayed session/tree/context GET và late model PATCH khỏi ghi đè lựa chọn mới; logout/đổi user dọn async refs. Model blur unchanged = 0 PATCH, changed = 1 PATCH |
| Regression artifact | `scripts/browser_v037.cjs` lưu 37 behavioral checks, URL/credentials cấu hình bằng env; `scripts/test_v037.py` có 8 static regression. Bundle mới `index-CnsaCxm0.js` + `index-C17X40lX.css` |

**Release gate:** 220/220 test (33 suite, gồm security + TUI), v0.37 8/8; fresh Chromium audit 20/20 + UX 37/37 + existing 14/14 + model-race 1/1 + signup 15/15 = 87/87; responsive matrix 5 viewport; mypy `engine/` + `server/` 39 files; TypeScript noEmit + Vite build 42 modules; bandit Medium+ 0. Ruff theo scoped gate với legacy findings được ghi rõ. Real Google OAuth, Docker/container smoke và nguồn 501 ngoài máy Windows vẫn chưa kiểm chứng.

## 3o. Hotfix v0.37.1 — Provider errors không được biến mất

Incident Windows có nhiều prompt nhưng không assistant/error. Read-only diagnostic trên máy user cho OpenRouter `HTTP 401` + `Missing Authentication header`; không dùng credential thật trong regression. Code audit xác định Web áp SSE error vào timeline rồi gọi `loadSession()`, thay timeline bằng `session.messages` và xoá cảnh báo vì error không được persist. Controlled mock khác tái hiện empty stream → `assistant_message: null`.

| Hạng mục | Vá + kiểm chứng |
|---|---|
| SSE error | Chỉ reload timeline sau stream không có error; giữ prompt + provider diagnostic. Fresh Chromium với SSE 401 giả lập: error vẫn visible sau 1.5s, prompt còn, không runtime error |
| Empty completion | Agent theo `finish_reason`; không content/tool call → `LLMError` actionable, không append assistant null. Test `finish=stop` đạt; completion `OK` đối chứng vẫn stream/lưu |
| Diagnostic | `scripts/diagnose_llm.py`: OpenRouter/Google, synthetic prompt, no tools/session writes, HTTP metadata + response tối đa 6.000 ký tự đã redact; Ruff/py_compile/mock self-test PASS |
| Phạm vi | Không thay secret store, provider headers, ACL/CSRF hay model routing. Hotfix làm lỗi nhìn thấy được; user vẫn phải sửa credential bị OpenRouter từ chối |

**Release gate:** 224/224 test (34 suite), hotfix 4/4; Chromium hotfix 1/1; mypy 39 files; TypeScript noEmit + Vite 42 modules; Bandit Medium+ 0. Baseline v0.37 Chromium 87/87 và responsive matrix 5 viewport giữ nguyên.

## 3p. v0.38.0 — Bilingual Web UI và English release assets

Mục tiêu là thêm English mà giữ tiếng Việt mặc định, không thay đổi quyền, provider routing hay phản hồi model thật. `LanguageProvider` bọc App, đọc/ghi `forge-language`, cập nhật `<html lang>` và cung cấp `t(vi, en)`. Login có VI/EN để người dùng mới chọn trước khi xác thực; Settings → Appearance có selector tương đương cho admin/member.

| Hạng mục | Thay đổi + kiểm chứng |
|---|---|
| Web coverage | App shell, Sidebar, Files/Terminal, Login, Tool/Approval/Elicitation cards và toàn bộ Settings tabs dùng translator cho text, placeholder, title/aria, errors và confirmations. AST scan không còn raw JSX tiếng Việt ngoài nhãn `Tiếng Việt` cố ý |
| Language contract | Chat/Batch/Battle body có optional `language`, mặc định `vi`; Web gửi lựa chọn hiện tại. Client cũ không gửi field vẫn nhận demo tiếng Việt |
| Demo + auth errors | `send_demo` đổi reasoning/intro/final theo ngôn ngữ nhưng vẫn ghi/chạy `hello_forge.py` thật. Login localize các lỗi auth đã biết. Provider output thật không bị ép dịch |
| Browser | 23/23 English checks: login, persistence, admin/member, validation, demo + workspace file, mobile; 37/37 UX tiếng Việt và 1/1 SSE hotfix chạy lại PASS, không runtime error |
| README assets | 3 PNG mới từ production English UI + account/workspace giả, không credential thật. Capture script scan visible text trên desktop agent/Settings/mobile và đã bắt/sửa `# ghi chú`, `<tên>`, `<ngày>` sót |

**Release gate:** 228/228 test (35 suite) trên working tree và ZIP giải nén; 149/149 file đối chiếu SHA-256; Chromium 37/37 + 23/23 + 1/1; mypy 39 files; TypeScript noEmit + Vite 43 modules; Bandit Medium+ 0; Ruff theo scoped gate với legacy findings đã ghi rõ. Ảnh 1440×1000 (desktop) và 390×844 (mobile) được đọc lại sau capture/optimize.

## 4. Việc còn lại (backlog theo mức ưu tiên)

| Ưu tiên | Việc | Vì sao |
|---|---|---|
| ~~P2~~ ✅ v0.17.2 | ~~TUI smoke~~ · ~~Audit log~~ · ~~Adversarial suite~~ | Đã làm — xem mục 3b |
| ~~P3~~ ✅ v0.18 (UI bảng + lọc) · **v0.30 nâng cấp v2**: quick-filter ✅/❌, cột phiên, click dòng xem args đầy đủ | UI có từ f60e42a — claim "còn P3" là stale, đã sửa |
| ~~P3~~ ✅ v0.27 | ~~mypy engine/~~ **0 lỗi / 32 file** (`python -m mypy engine/`) | gate thứ 3 xanh |
| P3 | Audit-log xuất CSV/JSON từ web (một nút) | tiện phân tích ngoài |

## 5. Kết luận

Dự án qua audit **đạt chuẩn an toàn OWASP LLM ở 6/6 mục trọng yếu với agent hành động thật**, không còn lỗi lint/bandit medium+, 90 test xanh. Fix quan trọng nhất là **bug crash CLI ẩn mình từ v0.15** (không ai mở CLI nên chưa phát hiện — bài học: test hồi quy phải phủ cả đường khởi động UI). Hiệu năng server tốt hơn hẳn nhờ bỏ 1 điểm blocking 90s.
