# 🧪 PROJECT_AUDIT — Rà soát toàn dự án theo chuẩn lập trình viên AI

> Ngày: 05/11/2026 · Commit sau audit: `b7049fd` (v0.17.1)
> **Phương pháp (không đoán):** ① Research khung chuẩn (OWASP Top 10 LLM 2025) → ② Đo bằng công cụ (ruff 0.17.3, bandit 1.9.4, coverage.py 7.17.2) → ③ Đọc code tại từng vị trí bị flag để xác nhận nguyên nhân gốc → ④ Sửa theo mức ưu tiên → ⑤ Chạy lại toàn bộ + thêm test hồi quy cho từng fix.

---

## 1. Nguyên tắc áp dụng (từ OWASP Top 10 cho LLM/Agent 2025)

| Mục OWASP | Ý nghĩa | forge-agent đạt nhờ | Trạng thái |
|---|---|---|---|
| **LLM01** Prompt Injection | Nội dung ngoài (email/web/skill) điều khiển model | Skills **trust gating** (v0.16), fetch_url chặn SSRF, approval gate | ✅ |
| **LLM02** Rò rỉ thông tin nhạy cảm | Token/PII lộ vào model/log | Secrets `data/secrets.json` chmod 600 + **mask mọi nơi**; token không vào system prompt (audit bằng grep: `agent.py` chỉ dùng key cho demo-check) | ✅ |
| **LLM05** Xử lý output thiếu kiểm soát | Output LLM chảy thẳng vào hệ thống thực thi | `guard.assess_command` chặn danger + **approval** cho warn (vẫn qua khi LLM "nghịch") | ✅ |
| **LLM06** Quá nhiều quyền/tự chủ *(rủi ro lớn nhất với agent)* | Agent làm việc thật không ai duyệt | Tool MCP chưa allowlist → **phải duyệt** (v0.17.0); `auto (YOLO)` là opt-in rõ ràng | ✅ |
| **LLM07** Lộ system prompt | Prompt chứa bí mật/logic mật | Prompt KHÔNG chứa secret (đã grep kiểm chứng) — prompt luôn coi như công khai | ✅ |
| **LLM10** Tiêu thụ không giới hạn | DoS / đốt tiền | Cap tool: buffer 60KB, fetch 20KB, todo 50 mục, skill ≤200, MCP CALL_TIMEOUT; **cost.py** hiển thị $ mỗi lượt | ✅ |

**Còn thiếu (ghi nhận, chưa làm):** audit log mọi tool call ra file (khuyến nghị OWASP), kiểm thử prompt-injection tự động (adversarial suite) — đưa vào backlog P2.

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

**Kết quả vòng 9: 134/134 test (22 suite) · bandit Medium+ 0 · ruff module mới sạch.**

## 3j. Vòng 10 (v0.26) — Skills trong web

| # | Mục | Kết quả thực đo |
|---|---|---|
| **S8** | **Tab 🧩 Skills trong ⚙ Cài đặt** | GET `/api/skills?sid=` (catalog + diagnostics) · POST `/api/skills/toggle` (bật/tắt model-invocation bằng frontmatter surgery — sửa/thêm/xoá `disable-model-invocation`, file legacy không frontmatter → tự tạo **đầy đủ name+description**) · POST `/api/skills/trust`; tab hiển thị nhóm nguồn, badge 🔒/🔕/⚠, nút Cấm/Cho model gọi + Tin skill |

**Bài học vòng 10 (2 lớp):** frontmatter tối thiểu khi tự tạo phải ĐỦ `name` **và** `description` — thiếu name → parse lệch; thiếu description → spec BỎ skill ("thiếu description → BỎ") khiến skill biến mất khỏi catalog. Test T2 bắt cả 2 lớp qua StopIteration → diagnostic in catalog/diags mới thấy nguyên nhân thật.

**Kết quả vòng 10: 139/139 test (23 suite) · bandit Medium+ 0 · ruff module mới sạch.**

## 3k. Vòng 11 (v0.27) — mypy về 0

| Mục | Kết quả thực đo |
|---|---|
| **mypy engine/ = 0 lỗi (32 file)** | Đo lại thấy baseline TRƯỢT XUỐNG 96 lỗi/7 file (v0.22–0.26 thêm autocommit/worktree/oauth nhưng chưa chạy mypy — vi phạm đúng quy tắc nhà). Sửa triệt để: (1) **narrow 1 chỗ ở nguồn** — `Agent.__init__` gán `self.session: Session = s0` sau raise → tắt 61/76 lỗi của agent.py; (2) pattern `GIT: str \| None` → gán biến cục bộ narrow trước `create_subprocess_exec` (checkpoints ×2, worktree); (3) `proc.returncode or 0` (returncode là `int \| None`); (4) tách biến list/str tái dùng trong autocommit (mypy bắt đúng chỗ code khó đọc); (5) `bool(result["ok"])` 2 chỗ log_tool; (6) sửa 1 bug tools.py thật: **ghi vào `proc.returncode` (property read-only) — thay bằng biến `hook_rc`**. Config chuẩn hoá `[tool.mypy]` trong pyproject.toml → `python -m mypy engine/` không cần flag |

**Kết quả vòng 11: 139/139 test (23 suite) · mypy 0 · bandit Medium+ 0 — 3 gate đều xanh.**

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

**Kết quả vòng 12: 144/144 test (24 suite) · mypy 0 · bandit Medium+ 0 · ruff connectors/mcp sạch.**

## 4. Việc còn lại (backlog theo mức ưu tiên)

| Ưu tiên | Việc | Vì sao |
|---|---|---|
| ~~P2~~ ✅ v0.17.2 | ~~TUI smoke~~ · ~~Audit log~~ · ~~Adversarial suite~~ | Đã làm — xem mục 3b |
| P3 | Audit-log UI trong web (bảng lọc theo phiên/tool) | hiện /audit là text; bảng đẹp hơn |
| ~~P3~~ ✅ v0.27 | ~~mypy engine/~~ **0 lỗi / 32 file** (`python -m mypy engine/`) | gate thứ 3 xanh |
| P3 | Audit-log xuất CSV/JSON từ web (một nút) | tiện phân tích ngoài |

## 5. Kết luận

Dự án qua audit **đạt chuẩn an toàn OWASP LLM ở 6/6 mục trọng yếu với agent hành động thật**, không còn lỗi lint/bandit medium+, 90 test xanh. Fix quan trọng nhất là **bug crash CLI ẩn mình từ v0.15** (không ai mở CLI nên chưa phát hiện — bài học: test hồi quy phải phủ cả đường khởi động UI). Hiệu năng server tốt hơn hẳn nhờ bỏ 1 điểm blocking 90s.
