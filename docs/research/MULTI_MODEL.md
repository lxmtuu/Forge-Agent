# 🔀 MULTI-MODEL ORCHESTRATION — Research & Thiết kế v0.13

> Ngày: 2026-11-04 · Trạng thái: **✅ ĐÃ TRIỂN KHAI trong v0.13 (commit đầy đủ 5 mục)**
> Nguyên tắc: research → kiểm tra → test → sửa

---

## 1. Forge ĐÃ CÓ gì về đa model (audit v0.12)

| Dạng | Cơ chế | Ghi chú |
|---|---|---|
| ⚔ **Battle** | Cùng 1 prompt chạy tối đa 4 model **song song**, mỗi model 1 session + workspace riêng | CLI `--battle`, web (ô nhập models), `/api/battle` |
| 📦 **Batch** | Nhiều nhiệm vụ, mỗi task 1 model tuỳ chọn, chạy song song | web + `/api/batch` |
| 🤖 **Custom agent** | `.forge/agents/<tên>.md` frontmatter `model:` → `/run` đè model phiên | v0.10 |
| 🧩 **Sub-agent** | tool `spawn_subagent(task, model?)` — model khác cho sub-agent, context riêng, workspace chung | v0.11 |
| 🎭 **Profiles** | `--profile safe/yolo` đè model + approval | v0.9 |
| 📇 **Catalog** | GET `/api/models` — 450+ model OpenRouter kèm giá, lọc free | v0.2+ |

**Khoảng trống so với chuẩn ngành** (xem §2): LLM không được *hướng dẫn* khi nào dùng model
nào; không có *alias* (LLM phải gõ đúng ID dài); sub-agent chạy *tuần tự*; *không cap* số
sub-agent; model lỗi 402/429 thì *chết luôn*, không fallback.

---

## 2. Research: đối thủ & chuẩn ngành

### 2.1 Claude Code — model routing cho subagents

- Frontmatter subagent: `model: haiku | sonnet | opus | inherit | <full-id>`.
- **Thứ tự phân giải model** (first-match-wins):
  1. Env `CLAUDE_CODE_SUBAGENT_MODEL` (ép toàn cục)
  2. Model truyền theo từng lượt gọi
  3. Frontmatter của subagent
  4. Model của phiên cha (inherit)
- **Bảng routing theo hình dáng việc**:
  | Việc | Model | Lý do |
  |---|---|---|
  | Tìm file, map symbol, tóm tắt log, check convention | **haiku** (rẻ) | đọc-only, kết quả khách quan |
  | Implement feature, fix bug, viết test, review diff thường | **sonnet** | lane code mặc định |
  | Quyết định kiến trúc, ràng buộc mâu thuẫn, audit rủi ro cao | **opus** (mạnh) | sai một phát trả giá |
  | Theo đúng model cha | **inherit** | khi nhất quán > chuyên biệt |
- Built-in: **Explore = Haiku + read-only** ("đừng đốt token Sonnet cho việc đọc file");
  Plan/general-purpose = inherit.
- Pattern song song: **Fan-Out** (nhiệm vụ độc lập chạy đồng thời), **Pipeline** (output agent
  này thành input agent kia), **Map-Reduce** (chia nhỏ → tổng hợp). Cấm lồng nhau (no nesting).
- ⚠️ Cảnh báo chi phí: routing chỉ có lợi khi việc *hẹp*; quá nhiều subagent đọc lại cùng
  repo → nhân chi phí lên nhiều lần.
- `opusplan`: hybrid ở cấp phiên — **plan bằng model mạnh, execute bằng model vừa**.

### 2.2 Anthropic multi-agent research system (orchestrator-worker)

- Lead (Opus) lập kế hoạch → spawn **3–5 subagent (Sonnet) song song** → tổng hợp; agent
  citation *riêng* kiểm chứng. Kết quả: **+90,2%** so 1 Opus đơn; **~15× token** (1 agent ≈ 4×).
- **Token usage tự nó giải thích 80% độ chênh chất lượng**; model là yếu tố 3 (đổi lên
  Sonnet 4 tốt hơn gấp đôi token budget trên model cũ).
- Task giao subagent phải **tự chứa hoàn toàn**: mục tiêu + format output + giới hạn
  công cụ + điều kiện xong.
- **Condensed return / artifact pattern**: subagent ghi chi tiết vào filesystem, chỉ trả về
  *tham chiếu + tóm tắt gọn* — không bơm nguyên văn lên lead (forge đã làm đúng điểm này:
  summary cap 4000 ký tự).
- **Bài học thất bại**: lead từng spawn 50 subagent cho câu hỏi đơn giản → phải **cap số
  lượng theo độ phức tạp**, cấm đệ quy, cap kích thước output công cụ. "Start small,
  measure cost per task, cap it."
- Khi nào **KHÔNG** nên multi-agent: cần chia sẻ context chặt, phụ thuộc tuần tự, budget
  ít, giá trị thấp. Việc *code* khó song song hoá — song song chỉ thật sự hợp cho
  **tìm kiếm/đọc hiểu/review độc lập**.

### 2.3 Routing & cascade — kinh tế học chi phí

- **RouteLLM** (Berkeley, ICLR'25): giảm **>85% chi phí**, giữ **95%** chất lượng GPT-4 —
  chỉ 14% query thực sự cần model mạnh. **FrugalGPT** (Stanford): cascade rẻ→đắt theo
  độ tin cậy, tiết kiệm **50–98%**.
- 3 chiến lược: **rule-based** (theo loại task — rẻ, cứng), **learned router** (classifier —
  cần dữ liệu), **cascade** (gọi rẻ trước, thang đo độ tin cậy quyết định leo lên model mạnh).
- **OpenRouter** (nền tảng forge đã dùng) có sẵn: `openrouter/auto` (Auto Router — tự chọn
  model theo prompt), Pareto Code Router (`min_coding_score` + session stickiness),
  Fusion Router (panel song song + tổng hợp), provider fallback tự động.
- ⚠️ Nguyên tắc kỹ thuật quan trọng: **tách bạch availability fallback** (model lỗi
  402/429/5xx → thử model khác) khỏi **quality routing** (chọn model theo độ khó) —
  chúng *fail khác nhau*, phải để riêng trong code và dashboard.
- Việc nhạy cảm/nguy hiểm cao → **pin cứng model mạnh**, không routing.

---

## 3. Thiết kế v0.13 "Multi-Model Orchestrator" (đề xuất)

| # | Mục | Thiết kế |
|---|---|---|
| 1 | **Alias model cho sub-agent** | `resolve_sub_model(x, parent)`: `""`/`inherit` → model cha · `cheap`/`free` → `config.model_roles.cheap` (mặc định: model free rẻ nhất đã cấu hình) · `strong` → `config.model_roles.strong` (mặc định: model phiên) · ID đầy đủ → nguyên bản |
| 2 | **Routing guidance** | Cập nhật spec `spawn_subagent` (description + param `model`): bảng "việc đọc/tìm kiếm → cheap · code thường → inherit · kiến trúc/review rủi ro → strong" — đúng cách Claude Code nhúng vào tool description |
| 3 | **Song song hoá** | Các `spawn_subagent` trong **cùng một lượt tool_calls chạy `asyncio.gather`** (tối đa 3 song song); nhiều model làm nhiều hướng độc lập — pattern Fan-Out |
| 4 | **Cap chống phình** | Tối đa **6 sub-agent/lượt** (thừa → tool message báo đã đạt giới hạn); giữ cấm đệ quy (depth) có từ v0.11 |
| 5 | **Availability fallback** | `llm.stream_chat`: lỗi 402/429/5xx → thử lại tối đa 1 model trong `config.model_fallbacks` (mặc định `[cheap]`); yield event `model_fallback {from, to, reason}` để 3 UI hiển thị; tách bạch khỏi quality routing |

Không làm ở v0.13 (cố tình): learned router/cascade tự build (OpenRouter đã có `auto`),
parallel file-edit bằng worktree (coding ít song song được — Anthropic cũng khuyến cáo),
Fusion-style panel (đã có ⚔ Battle).

**Tiêu chí nghiệm thu**: test smoke đầy đủ (alias, song song, cap, fallback với fake LLM),
regression 55/55, UI tiếng Việt hiện event mới, zip mới.

> **Kết quả v0.13:** smoke 6/6 PASS (đo thời gian chứng minh fan-out song song thật:
> 2 sub-agent 0.45s chạy trong ~0.5s thay vì 0.9s tuần tự) · regression 16+12+8+9+5+5 = 55/55 ·
> TUI OK · py_compile OK. Bài học debug: bug "chạy tuần tự?" hoá ra là BUG TEST (route fake-LLM
> bằng `"việc" in text` — tool result chứa chữ "việc" làm lượt tổng hợp của cha bị tưởng là sub).

---

## 4. Nguồn

- Claude Code subagents frontmatter + model routing (prg.sh, buildthisnow, gist danielrosehill, baeseokjae 2026)
- Anthropic "How we built our multi-agent research system" (phân tích: theaiengineer.substack, cuizhanming, dev.to sebastian_chedal, molderez-consult)
- Routing/cascade: neuraltrust (RouteLLM/FrugalGPT), iotdigitaltwinplm (taxonomy + OpenRouter Auto), niteagent (router layer), dev.to shaam_ai (Auto/Pareto/Fusion router)
