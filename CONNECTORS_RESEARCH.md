# 🔬 CONNECTORS_RESEARCH — Kết nối Gmail/GitHub/Notion/... cho tự động hoá

> Ngày research: 05/11/2026 · Câu hỏi: **"forge-agent có hỗ trợ connectors (GitHub, Gmail,…) để làm việc tự động không?"**
> Trả lời ngắn: **CÓ — và đừng tự viết từng connector.** Chuẩn ngành 2026 đã hội tụ về **MCP**: mỗi SaaS (GitHub, Notion, Linear, Supabase, Vercel…) tự chạy **remote MCP server** chính thức; agent chỉ cần trỏ URL + token. forge-agent **đã có sẵn MCP client (stdio + HTTP)** từ trước → việc còn lại là lớp **"connector"** (preset sẵn + quản trị token + an toàn duyệt lệnh), không phải viết integration từng app.

---

## 1. Thực trạng forge-agent (audit code — *bản chụp lúc research, trước v0.17*)

> ⚠️ **Đây là bản chụp lịch sử.** Cột "Hiện trạng v0.31" ghi lại từng dòng ĐÃ ĐÓNG ở version nào — kiểm chứng lại 05/11/2026 bằng code + test thật (test_v017 T3/T4 xanh): gate approval thực thi tại `engine/agent.py:609`, secrets mask tại `engine/connectors.py` (`mask_token`, `auth()`), OAuth tại `engine/oauth.py`.

| Thành phần | Trạng thái *lúc audit* | Ghi chú *lúc audit* | Hiện trạng v0.31 |
|---|---|---|---|
| MCP client **stdio** (`McpServer`) | ✅ có (`engine/mcp.py`) | chạy `npx`/`docker` server local, JSON-RPC | ✅ giữ nguyên + `$VAR` expansion lúc spawn (v0.28) |
| MCP client **HTTP** (`McpHttpServer`) | ✅ có | trỏ URL + `headers` (Bearer token) | ✅ giữ nguyên — Stripe/Atlassian/Vercel/Supabase remote |
| Gắn tool MCP vào vòng lặp agent | ✅ có | tool prefix `mcp_<srv>_…`, event `mcp_ready` | ✅ giữ nguyên |
| MCP **elicitation** (server hỏi giữa chừng) | ✅ có | đẩy `elicitation_request` lên UI | ✅ giữ nguyên |
| Cấu hình | ⚠️ tay | `data/mcp.json` — phải tự soạn JSON | ✅ **ĐÓNG v0.17 (C1) + v0.29**: 18 preset — `/connectors add <tên>`, REST + tab ⚙ (không ai phải soạn JSON nữa) |
| **Token/secrets** | ❌ chưa có | chưa có chỗ lưu, chưa mask | ✅ **ĐÓNG v0.17 (C3)**: `data/secrets.json` chmod 600 + `mask_token()` mọi listing — test T2 chứng minh token thật 0 lần echo |
| **Approval cho tool MCP** | ❌ **lỗ hổng** | tool MCP gọi THẲNG không qua duyệt | ✅ **ĐÓNG v0.17 (C4)**: tool chưa allowlist → `approval_request` như `run_command` (gate `agent.py:609`); allow per-tool/`*`; deny rút phép — test T3/T4 chứng minh live |
| OAuth 2.1 (đăng nhập remote server) | ❌ chưa | Notion/Supabase/Vercel mặc định OAuth | ✅ **ĐÓNG v0.20/v0.21 (C6)**: `engine/oauth.py` — authorization code + **PKCE S256** (RFC 7636) trên loopback (RFC 8252), `/connectors oauth <tên> <client_id> [secret]` |
| Lệnh/UI quản lý connector | ❌ chưa | chỉ `/mcp` xem danh sách | ✅ **ĐÓNG v0.17 (C2) + v0.21 (C7)**: `/connectors add|auth|allow|deny|remove|oauth` đủ CLI/TUI/Web + tab ⚙ 📡 Kết nối / 🔗 Dịch vụ |

**Kết luận audit lúc đó:** "engine" đã xong ~70%; thiếu lớp trải nghiệm + an toàn. **→ Đã bổ sung xong toàn bộ ở v0.17/v0.20/v0.21 (C1→C7), mở rộng 11→18 preset ở v0.28/v0.29.** Không còn mục nào đỏ.

## 2. Bản đồ connectors 2026 (ai cung cấp gì)

### 2.1 Remote MCP chính thức (first-party) — trỏ URL là chạy

| Dịch vụ | Endpoint | Auth | Ghi chú |
|---|---|---|---|
| **GitHub** | `https://api.githubcopilot.com/mcp/` | **PAT** (Bearer) hoặc OAuth | repos/PR/issues/Actions; có bản Docker cho enterprise |
| **Linear** | `https://mcp.linear.app/mcp` (+ `/mcp/readonly`) | OAuth 2.1 **hoặc API key** | issue/project/cycle; tool description chuẩn, agent dùng ổn định |
| **Supabase** | `https://mcp.supabase.com/mcp` | OAuth | hỗ trợ `?read_only=true` và `project_ref=` — nên bật với dữ liệu thật (chính Supabase cảnh báo prompt injection qua dữ liệu bảng) |
| **Notion** | `https://mcp.notion.com/mcp` | **chỉ OAuth** | đã thay bản self-host cũ, trả kết quả gọn token hơn |
| **Vercel** | `https://mcp.vercel.com` | OAuth | ⚠️ **chỉ nhận client được Vercel duyệt** (Claude Code, Codex, Cursor…) → forge-agent tự-host **không nối trực tiếp được**, phải qua hub |
| Slack, Figma, Stripe, Sentry, Atlassian, Cloudflare, Neon, Hugging Face | remote | OAuth/PAT | roster chính thức vẫn đang lớn dần |
| **Gmail** | ❌ **không có remote chính thức của Google** | — | đường đi thực tế: hub (Composio/Pipedream) hoặc server cộng đồng `npx` (App Password/OAuth tự cấu hình) |

### 2.2 Hub "managed OAuth" — 1 kết nối, nghìn app, không tự làm OAuth

| Hub | Apps | Auth | Free tier | Transport |
|---|---|---|---|---|
| **Composio** | ~500–1000 toolkit (Gmail, Slack, GitHub, Notion, Salesforce…) | **managed OAuth** — token mã hoá, tự refresh, **không lộ cho LLM** | 20k calls/tháng | stdio + HTTPS, self-host được (MIT) |
| **Pipedream MCP** | 2.800+ API | managed OAuth | 100 credits | HTTP/SSE/stdio |
| **Zapier MCP** | 8.000+ app | managed (theo Zapier sẵn có) | 100 tasks/tháng | HTTPS |

→ **Với Gmail/Slack/Vercel**: đi qua hub là nhanh và an toàn nhất (OAuth do hub lo).

### 2.3 Đối chiếu với bảng Connectors trong Arena (màn hình bạn gửi)

Arena hiển thị Dropbox/Gmail/Docs/Drive/Sheets/Slides/Linear/Notion/Supabase/Vercel — mô hình y hệt: **mỗi app = 1 connector có auth riêng**. forge-agent tự-host làm được cùng thứ đó nhờ MCP: preset GitHub/Linear/Supabase/Notion nối thẳng (PAT/API key/OAuth), Gmail/Slack/Vercel qua hub. (Riêng trong chat Arena này, mình có sẵn connector Gmail/Drive/Docs/… nhưng **không có GitHub** — nên xây connector cho forge-agent còn phục vụ chính công việc repo của mình.)

## 3. Thiết kế đề xuất cho forge-agent

### Kiến trúc 3 lớp (tận dụng engine MCP sẵn có)

```
/connectors  ──►  [Lớp 1] CONNECTOR PRESETS  (khai báo: endpoint, transport, kiểu auth, hướng dẫn)
                        │
                        ▼
              [Lớp 2] engine/mcp.py (đã có)  ── stdio / HTTP+headers ──► SaaS
                        │
                        ▼
              [Lớp 3] An toàn: secrets mã hoá-at-rest + APPROVAL cho tool MCP
```

- **Preset** = object JSON: `{name, label, endpoint, transport: http|stdio, auth: pat|api-key|oauth|hub, headers/env mẫu, read_only_hint, docs}` — bản thân connector KHÔNG chứa code riêng.
- **Token** lưu `data/secrets.json` (quyền 0600, mask khi hiển thị `ghp_****`), **không bao giờ** đưa vào system prompt/tool result cho LLM.
- **Approval MCP (mới — vá lỗ hổng)**: chế độ `guarded` → tool MCP **chưa allowlist** phải duyệt như `run_command`; allowlist theo server hoặc per-tool (`/connectors allow …`); tool có tên gợi ý đọc (`search_*`, `list_*`, `get_*`) có thể auto-allow cấu hình được.
- **UX**: `/connectors` (liệt kê + trạng thái + số tool) · `/connectors add github` · `/connectors auth github <PAT>` · `/connectors remove` · `/connectors allow|deny`; `/doctor` thêm mục kiểm tra connector (ping, đếm tool).
- **OAuth 2.1 loopback (P1)**: mở browser → callback `localhost:PORT` → đổi code lấy token, refresh tự động — chuẩn mà Notion/Linear/Supabase dùng; chạy tốt trên Windows (chỉ cần mở browser mặc định).

### Rủi ro & hoá giải

| Rủi ro | Mức | Hoá giải |
|---|---|---|
| Tool MCP = hành động thật (gửi mail, sửa DB) chạy không hỏi | **Cao nhất** | Approval mặc định cho tool chưa allowlist (vá ngay ở P0) |
| Prompt injection từ dữ liệu SaaS (email/ticket độc) | Cao | `read_only` endpoint khi chỉ đọc (Linear/Supabase có sẵn); approval hành động ghi; nhắc user scope token tối thiểu |
| Secret lộ qua log/output | Trung bình | mask trong mọi hiển thị; secrets không vào context LLM |
| Vercel chặn client chưa duyệt | Nhỏ | preset "qua Composio" thay cho nối thẳng |
| Server cộng đồng (Gmail npx) kém tin | Trung bình | khuyến nghị hub; ghi nguồn + cảnh báo trong preset |

## 4. Đề xuất gói v0.17 "Connectors"

| Mức | Mục | Nội dung | Ước lượng |
|---|---|---|---|
| **P0 ✅ ĐÃ LÀM** | **C1 · Presets** | Catalog ~12 connector: GitHub (PAT), Linear (API key), Supabase (read_only), Notion (hub/OAuth-P1), Gmail+Slack+Vercel (hub), Sentry, Stripe, Figma (Desktop MCP), Context7, Playwright (stdio) | ~0.5 ngày |
| **P0 ✅ ĐÃ LÀM** | **C2 · Lệnh /connectors** | `add · auth · list · status · remove · allow/deny` chạy đồng bộ CLI/TUI/Web (synthetic như /skills) | ~1 ngày |
| **P0 ✅ ĐÃ LÀM** | **C3 · Secrets** | `data/secrets.json` (0600), mask mọi nơi hiển thị, không vào context LLM | ~0.5 ngày |
| **P0 ✅ ĐÃ LÀM** | **C4 · Approval MCP** | guarded: tool MCP chưa allowlist → duyệt như run_command; `/doctor` thêm check connectors | ~0.5 ngày |
| **P1** | **C5 · Hub Composio** | preset hub + flow nối Gmail/Slack/Vercel qua Composio (free 20k calls) | ~0.5 ngày |
| **P1** | **C6 · OAuth 2.1 loopback** | tự đăng nhập remote server (Notion/Linear/Supabase), refresh token | ~1.5 ngày |
| **P1** | **C7 · Tab Connectors trong Settings web** | thêm/bật/tắt/status trực quan | ~1 ngày |
| **P2** | C8 | allowlist per-tool tinh chỉnh, auto-allow tool đọc, marketplace sync | — |

**Đã giao (P0, v0.17):** smoke 6/6 ×2 + regression 85 test xanh — 9 presets, /connectors đầy đủ, secrets mask (0 lần echo token trong E2E), approval MCP + approve_always. Kỳ vọng ban đầu: gõ `/connectors add github` + dán PAT → nói *"đóng issue #12 với lý do X"* là agent làm được qua GitHub thật; thêm hub → Gmail/Slack tự động hoá thư mà không cần tự làm OAuth.

## 5. Nguồn

- openhelm.ai — "Best Remote MCP Servers 2026": endpoint chính thức GitHub/Notion/Linear + Slack/Figma/Stripe/Cloudflare
- eseospace.com — GitHub PAT/OAuth, Vercel **approved-clients-only**, Supabase `read_only` + cảnh báo prompt injection, Linear API key
- mcp.so — bảng 25 server chính thức (endpoint, transport, auth)
- hatchable.com — `claude mcp add` cho Supabase, Linear mở rộng initiatives 2026
- chatforest.com / siftaitools.com / nango.dev — so sánh Composio vs Pipedream vs Zapier MCP (managed OAuth, free tier, self-host)
