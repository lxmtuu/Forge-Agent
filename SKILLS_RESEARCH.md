# 🔬 SKILLS_RESEARCH — Agent Skills 2026 & khả năng áp dụng vào forge-agent

> Ngày research: 05/11/2026 · Câu hỏi: **"Agent Skills hiện nay như thế nào, forge-agent áp dụng và phát triển được không?"**
> Trả lời ngắn: **Áp dụng được và RẤT NÊN** — đây là chuẩn mở chính thức (đã quyên cho Linux Foundation, 70+ nền tảng theo). Forge-agent có sẵn nền từ v0.11 nhưng **lệch chuẩn ở 4 điểm then chốt** → nâng cấp vừa phải, không phải viết lại.
> 🔄 **Đối chiếu 05/11:** các mục ❌ trong bảng §lệch chuẩn đã đóng: #12 trust ✅ S5 v0.26 · #13 marketplace `/skills add` ✅ v0.16 · #14 lệnh `/skills` ✅ v0.16 — phần *Đã giao* cuối file; định dạng thư mục chuẩn đã hỗ trợ song song cả dẹt lẫn `<tên>/SKILL.md` (S8 v0.26).

---

## 1. Agent Skills là gì?

Một **skill = một thư mục**, bên trong có file `SKILL.md` (YAML frontmatter + Markdown hướng dẫn), tùy chọn kèm `scripts/`, `references/`, `assets/`. Agent lúc khởi động chỉ đọc **tên + mô tả** (~30–100 tokens/skill); khi nhiệm vụ khớp mô tả mới nạp toàn bộ nội dung; tài nguyên đi kèm chỉ đọc khi được dẫn tới; **script thì chạy trực tiếp qua shell — chỉ output tốn token, code thì không**.

### Progressive disclosure — 3 tầng (điểm ăn tiền của cả chuẩn)

| Tầng | Chứa gì | Khi nào nạp | Chi phí token |
|---|---|---|---|
| 1 · Catalog | `name` + `description` | Ngay khi bật phiên | ~50–100/skill |
| 2 · Body SKILL.md | Quy trình, ví dụ, checklist | Khi mô tả khớp nhiệm vụ | < 5.000 (khuyến nghị) |
| 3 · Resources | scripts/ references/ assets/ | Khi body dẫn tới | 0 cho tới khi dùng |

→ Cài 50 skill vẫn gần như "miễn phí" nếu chỉ dùng 2 skill trong phiên. Đây chính là lý do chuẩn này thắng thế so với nhồi everything vào system prompt.

### Skill ≠ Commands ≠ MCP

| | Skill (SKILL.md) | Slash command | MCP server |
|---|---|---|---|
| Bản chất | **Tri thức quy trình** model tự đọc khi khớp | Prompt mở rộng gọi tay | **Công cụ** gọi qua protocol |
| Ai kích hoạt | Model (hoặc `/tên` như alias) | Chỉ người dùng | Model (qua tool call) |
| Tốn context | Gần như 0 khi không dùng | Chỉ khi gọi | Chi phí kết nối/mô tả tool |
| Đi kèm tài nguyên | Có (scripts/references) | Không | Server tự lo |

MCP đang có working-group "skills over MCP" — hai bên hợp tác thay vì cạnh tranh.

---

## 2. Timeline — vì sao đây là chuẩn "đỡ hụt trend"

| Thời điểm | Sự kiện |
|---|---|
| 10/2025 | Anthropic ra mắt Skills trong Claude Code/Claude apps/API |
| **18/12/2025** | Phát hành **chuẩn mở** tại agentskills.io + SDK + validator `skills-ref validate` |
| Sau 48 giờ | Microsoft đưa vào VS Code/Copilot; OpenAI đưa vào ChatGPT + Codex CLI (repo 20k ⭐) |
| 20/01/2026 | Vercel mở **skills.sh** — marketplace + CLI `npx skills add <author>/<skill>` (đã ~90.000 skills; top skill 20k cài trong 6 giờ) |
| 01/2026 | Claude Code 2.1.0 thêm **hot-reload** skill (sửa file là thấy, không cần restart) |
| 02–03/2026 | AWS Kiro, Gemini CLI, JetBrains Junie, Block Goose, Amp, Snowflake, Databricks, ByteDance TRAE… → **32 tools** |
| 22/10/2026 | Anthropic **tặng Agent Skills cho AAIF / Linux Foundation** (cùng nhà với MCP, AGENTS.md, Goose) — format KHÔNG đổi |

Tính 8/2026: trang client-showcase của chuẩn liệt kê **46 sản phẩm**; Anthropic công bố **70+ nền tảng** đã tích hợp. Partner launch: Atlassian, Figma, Canva, Stripe, Notion, Zapier, Cloudflare, Sentry…

**Ý nghĩa với forge-agent:** làm theo chuẩn = hàng chục nghìn skill có sẵn trên skills.sh / anthropics/skills (19 skill) / openai/skills (39 skill) **chạy được luôn**, không phải tự viết hết. Simon Willison lưu ý spec "còn khá mở" ở vài chỗ (allowed-tools experimental) — nhưng phần format cốt lõi thì mọi client đều alike.

---

## 3. Spec kỹ thuật rút gọn (phiên bản mình cần biết để làm)

### 3.1 Cấu trúc & frontmatter

```
my-skill/
├── SKILL.md          ← bắt buộc, tên file CHÍNH XẠ hết chữ hoa
├── scripts/          ← script chạy được (agent gọi qua shell)
├── references/       ← tài liệu tham khảo (nạp khi cần)
└── assets/           ← template, file tĩnh
```

| Trường | Bắt buộc | Ràng buộc |
|---|---|---|
| `name` | ✅ | `[a-z0-9-]`, ≤64 ký tự, **phải khớp tên thư mục cha**, không bắt/kết bằng `-`, không `-` liền; không chứa "anthropic"/"claude" |
| `description` | ✅ | ≤1.024 ký tự, **không có dấu `<` `>`**; phải nói rõ **làm gì + khi nào dùng** (đây là "trigger") |
| `license` | — |VD `Apache-2.0` |
| `compatibility` | — | ≤500 ký tự, yêu cầu môi trường |
| `metadata` | — | map string→string tuỳ ý |
| `allowed-tools` | — | ⚗️ experimental: chuỗi cách nhau bởi dấu cách = tool được phép dùng |

### 3.2 Quy tắc validate "lenient" (khuyến nghị của chuẩn)

- `name` lệch tên thư mục / quá 64 ký tự → **cảnh báo, vẫn nạp**
- Thiếu/rỗng `description` → **bỏ skill, log lỗi** (không có mô tả = không có trigger)
- YAML vỡ hoàn toàn → bỏ, log
- Lỗi YAML phổ biến nhất: giá trị chưa quote chứa dấu `:` → client nên có **fallback tự quote rồi đọc lại**

### 3.3 Hướng dẫn cho client-agent (trang chính thức "adding skills support")

1. **Quét 2 scope**: project + user (`~`), trong mỗi scope quét cả **thư mục riêng của client** và **`.agents/skills/`** (quy ước cross-client — Codex/Cursor/Copilot/Gemini CLI đều đọc); nhiều client còn quét `.claude/skills/` vì kho skill sẵn có nằm đó.
2. **Giới hạn quét**: bỏ `.git/`, `node_modules/`; depth ≤4–6; ≤2000 thư mục.
3. **Trùng tên**: **project đè user** — bắt buộc; trong cùng scope thì nhất quán 1 chiều + **log cảnh báo**.
4. **Trust gating**: skill project-level đến từ repo (có thể là repo lạ vừa clone) → nên chỉ nạp khi **thư mục được đánh dấu tin tưởng**, tránh prompt-injection từ repo ngoài.
5. **Catalog vào system prompt** (đơn giản, hợp mọi agent có tool đọc file) kèm lời dẫn: "khi nhiệm vụ khớp, hãy đọc SKILL.md tại đường dẫn; **path tương đối trong skill giải theo thư mục của skill**". Skill bị tắt/`disable-model-invocation` → **ẩn hẳn khỏi catalog**. Không có skill nào → bỏ nguyên khối, không render rỗng.
6. Hoạt hoá: model đọc file SKILL.md qua tool đọc file (forge đã có `read_file`) — hoặc tool riêng `activate_skill` (cách "sạch" hơn, OpenCode đi đường này với native skill tool).

### 3.4 Bảng vị trí quét của các client hiện hành

| Client | Project | User | Ghi chú |
|---|---|---|---|
| Claude Code | `.claude/skills/` | `~/.claude/skills/` | chuẩn gốc, kho skill lớn nhất |
| OpenAI Codex | `.agents/skills/` | `~/.codex/skills/` | cap 50MB zip / 500 file / version |
| OpenCode | `.opencode/skills/` + `.claude/skills/` + `.agents/skills/` | `~/.config/opencode/skills/` + tương tự | walk-up tới git root; skill có `deny` → ẩn |
| Gemini CLI | — | `~/.gemini/skills/` | cũng đọc `.agents/skills/` |
| Copilot / VS Code | `.github/skills/`? + `.agents/skills/` | user settings | đọc cùng format |
| Cursor | project-level | `~/.cursor/skills/` | docs riêng |

→ **Quy ước gold**: client dir riêng **+** `.agents/skills/` **+** `.claude/skills/` cho tương thích ngược.

### 3.5 Best practices viết skill (từ Anthropic + nghiên cứu độc lập)

- `description` viết như **trigger**: gồm cả "làm gì" và "khi nào dùng", dám "pushy" — nghiên cứu arXiv trên 238 skill thật: **99% có ít nhất 1 "skill smell"** và đa số do mô tả mơ hồ.
- Body **< 5.000 tokens**: quy trình từng bước, checklist, mục "gotchas" (bẫy thường gặp); **"cung cấp mặc định, không đưa menu lựa chọn"**.
- Lệnh phức tạp → đóng vào `scripts/` (không interactive, có `--help`); skill chứa **tri thức ổn định**, không chứa dữ liệu đổi theo lần gọi.
- Cài sẵn skill **skill-creator** (Anthropic) để agent tự viết skill mới khi người dùng yêu cầu — vòng lặp tự phục vụ.

---

## 4. 🔍 Audit forge-agent hiện tại (v0.11) so với chuẩn

Code: `engine/skills.py` (84 dòng) + alias trong `engine/commands.py` + `skills_block()` trong system prompt.

| # | Tiêu chí chuẩn | forge-agent hiện tại | Trạng thái |
|---|---|---|---|
| 1 | Thư mục `<tên>/SKILL.md` | File dẹt `.forge/skills/<tên>.md` | ❌ **lệch chuẩn** — skill tải từ mạng phải bóc lại mới chạy |
| 2 | Frontmatter `name` khớp thư mục | Không có field `name` (lấy từ tên file) | ❌ |
| 3 | YAML thật (metadata map, license, compatibility) | Regex dòng `key: value` — chỉ hiểu `description` + `disable-model-invocation` | ⚠️ thiếu |
| 4 | Tầng 1 catalog (~50–100 tokens) + lời dẫn | ✅ Có — name+description + hướng dẫn đọc file | ✅ đúng tinh thần |
| 5 | Tầng 2 nạp body khi khớp | ✅ LLM tự `read_file` | ✅ (khác: nạp nguyên file, không cap 5k) |
| 6 | Tầng 3 scripts/references/assets | Không có trong catalog; LLM có shell nên chạy được **nếu biết** — nhưng catalog không nói | ❌ |
| 7 | Đa vị trí: client dir + `.agents/skills/` + `.claude/skills/`, project+user | Chỉ `.forge/skills/` (project) + `data/forge/skills/` (global) | ❌ **không thấy skill cài bởi Claude Code/Codex/OpenCode** |
| 8 | Precedence + cảnh báo trùng tên | ✅ project đè global (không cảnh báo) | ⚠️ |
| 9 | Lenient validation + diagnostics | Im lặng bỏ skill thiếu description | ⚠️ không có diagnostics |
| 10 | `/tên` gọi tay + `$ARGUMENTS` | ✅ có qua commands.py | ✅ |
| 11 | disable-model-invocation → ẩn catalog | ✅ có | ✅ |
| 12 | Trust gating skill project-level | Không | ❌ |
| 13 | Cài từ marketplace (skills.sh/git) | Không | ❌ |
| 14 | Lệnh liệt kê skill (/skills) | Không (chỉ block trong system prompt) | ❌ |
| 15 | Hot-reload | ✅ tự có — `_skills_block()` đọc lại mỗi turn | ✅ |

**Điểm mạnh giữ lại:** kiến trúc progressive-disclosure đúng sẵn; đường dẫn `pathlib` chạy Windows OK; gọi tay `/tên` đã tiện; hot-reload miễn phí.

**4 lỗ hổng lớn:** (1) format file dẹt ≠ chuẩn thư mục → **không cài được skill của hệ sinh thái**; (2) chỉ quét 1 vị trí → kho skill 90k của thị trường bỏ phí; (3) frontmatter parser không hiểu YAML đầy đủ; (4) không có tooling cài/validate/liệt kê.

---

## 5. Đánh giá khả năng phát triển (kỹ thuật + rủi ro)

### Làm được ngay, chi phí thấp
- **Format mới + tương thích ngược**: quét cả `<tên>/SKILL.md` (chuẩn) lẫn `<tên>.md` (cũ) — người dùng cũ không vỡ gì. `pyyaml` cần thêm vào `requirements.txt` (sandbox đã có 6.0.3; máy Windows phải `pip install` — thêm 1 dòng requirements là xong), kèm **fallback tự-quote giá trị có `:`** đúng khuyến nghị của chuẩn.
- **Đa vị trí quét**: cộng thêm `.agents/skills/`, `.claude/skills/`, `~/.forge/skills/` — thuần `Path.glob`, có bounds depth/count như khuyến nghị.
- **`/skills` + validate**: nhận diện tên kebab-case, `name` vs thư mục, mô tả ≤1024 không `<`, body cảnh báo >5k tokens (~20k ký tự), phát hiện YAML vỡ.
- **Tài nguyên**: catalog ghi kèm đường dẫn tuyệt đối của `scripts/` `references/` khi tồn tại + dòng "chạy script bằng tool shell, path tương đối giải theo thư mục skill".

### Rủi ro & cách hoá giải
| Rủi ro | Mức | Hoá giải |
|---|---|---|
| Skill từ repo lạ = **prompt injection** | Cao nhất | Trust gating: lần đầu thấy skill project mới → hiện cảnh báo + cần xác nhận (lưu vào settings); `/skills add` luôn hỏi xác nhận + validate trước khi ghi |
| Script trong skill chạy shell | Trung bình | Vẫn qua **guard danger sẵn có** của tool shell (không opening quyền gì mới); catalog nhắc skill phải script non-interactive |
| YAML vỡ từ skill người khác viết | Trung bình | Fallback tự-quote + lenient (cảnh báo, vẫn nạp) |
| Trùng tên nhiều nguồn | Thấp | precedence project > `.agents` > `.claude` > `.forge` global > user home, in cảnh báo khi shadow |
| Token catalog phình khi cài nhiều | Thấp | cap mô tả 200 ký tự hiện nay → nâng 1.024 nhưng cắt ở catalog; ẩn skill tắt |

### Không nên theo ở vòng này
- Publish skill lên skills.sh (cần account Vercel — ngoài tầm tự-host); skill-over-MCP working group; allowed-tools thực thi cứng (còn experimental — chỉ đọc hiển thị); UI marketplace đầy đủ trong app.

---

## 6. 📦 Đề xuất gói v0.15 "Skills 2.0"

| Mức | Mục | Nội dung | Ước lượng |
|---|---|---|---|
| **P0 ✅ ĐÃ LÀM** | **S1 · Chuẩn hoá format** | Quét `<tên>/SKILL.md` + tương thích ngược `<tên>.md`; frontmatter **pyyaml** + fallback tự-quote; fields name/license/compatibility/metadata; lenient validate + diagnostics | ~1 ngày |
| **P0 ✅ ĐÃ LÀM** | **S2 · Đa vị trí quét** | `.forge/skills` + `.agents/skills` + `.claude/skills` (project, walk-up tới git root) + `~/.forge/skills` (user); precedence + cảnh báo shadow; bounds depth≤6/≤2000 dir | ~1 ngày |
| **P0 ✅ ĐÃ LÀM** | **S3 · Tooling** | Lệnh `/skills` (liệt kê nguồn+nqués trùng); `/skills add <thư mục git>` = clone về user scope + validate + hỏi trust; skill mẫu `commit-vn` kèm repo; cập nhật README | ~1 ngày |
| **P1 ✅ ĐÃ LÀM** | **S4 · Resources** | Catalog nêu scripts/references/assets + hướng dẫn chạy script qua shell (qua guard danger); test skill có script thật | ~0.5 ngày |
| **P1 ✅ ĐÃ LÀM** | **S5 · Trust gating** | Lần đầu nạp skill project-level mới → cảnh báo + cần đồng ý (ghi nhớ theo workspace); danh sách skill đã tin trong `/skills` | ~0.5 ngày |
| **P1 ✅ ĐÃ LÀM** | **S6 · skill-creator** | Skill built-in chuẩn Anthropic (viết lại tiếng Việt hoà blend): agent tự dựng skill mới theo spec khi được yêu cầu | ~0.5 ngày |
| **P2** | S7 · allowed-tools hiển thị | Đọc + hiển thị trong /skills (chưa thực thi) | nhỏ |
| **P2** | S8 · **✅ ĐÃ LÀM v0.26** Tab Skills trong Settings web | catalog + bật/tắt model-invocation (frontmatter surgery) + trust + diagnostics | xong |

**Đã giao (P0):** smoke 6/6 ×2 + regression 67 xanh. **Đã giao (P1, v0.16):** smoke 6/6 ×2 + regression 79 xanh — catalog nêu tài nguyên + thư mục gốc, trust gating (blocked_reason + bịt bypass alias), skill-creator built-in.; `/skills add anthropics/skills` cài thật 13 skill Anthropic 13/13 pass validate. Kỳ vọng ban đầu: skill viết cho Claude Code/Codex/OpenCode **chạy thẳng** trong forge-agent; cài được từ bất kỳ repo git nào; tính reachability với hệ sinh thái ~90k skill có sẵn.

---

## 7. Nguồn

- agentskills.io — specification + client-implementation guide "adding-skills-support" (fetch 05/11/2026)
- deepwiki.com/anthropics/skills — SKILL.md format spec (frontmatter constraints, validation)
- ccleaks.com — Anthropic donate Agent Skills → AAIF/Linux Foundation 22/10/2026
- paperclipped.de — 48-hour adoption chain, 32 tools 03/2026, skills.sh số liệu
- skillsboard.sh — client showcase 46 sản phẩm (8/2026), quy ước `.agents/skills/`
- opencode.ai/docs/skills — vị trí quét OpenCode (01/11/2026)
- strapi.io / firecrawl.dev / productbuilder.net — tổng hợp 26–70+ adopters, AAIF
- atlan.com — giới hạn trường, nghiên cứu arXiv 2607.01456 (99% skill smells)
- pdf4.dev — hot-reload Claude Code 2.1.0 (01/2026), cap Codex 50MB/500 files
