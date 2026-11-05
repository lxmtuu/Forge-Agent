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

## 4. Việc còn lại (backlog theo mức ưu tiên)

| Ưu tiên | Việc | Vì sao |
|---|---|---|
| ~~P2~~ ✅ v0.17.2 | ~~TUI smoke~~ · ~~Audit log~~ · ~~Adversarial suite~~ | Đã làm — xem mục 3b |
| P3 | Audit-log UI trong web (bảng lọc theo phiên/tool) | hiện /audit là text; bảng đẹp hơn |
| P3 | mypy dần dần cho engine/ (bắt đầu từ tools.py, agent.py) | bắt lỗi kiểu sớm hơn ruff |
| P3 | ASYNC240 → `to_thread` cho lsp/review khi có dư địa | nhất quán async thuần |

## 5. Kết luận

Dự án qua audit **đạt chuẩn an toàn OWASP LLM ở 6/6 mục trọng yếu với agent hành động thật**, không còn lỗi lint/bandit medium+, 90 test xanh. Fix quan trọng nhất là **bug crash CLI ẩn mình từ v0.15** (không ai mở CLI nên chưa phát hiện — bài học: test hồi quy phải phủ cả đường khởi động UI). Hiệu năng server tốt hơn hẳn nhờ bỏ 1 điểm blocking 90s.
