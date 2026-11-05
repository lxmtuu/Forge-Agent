# 📇 MCP Catalog — 18 preset của forge-agent (v0.29, research 2026-11)

> Thêm nhanh: `/connectors add <tên>` · Xem tool: `/mcp` · Duyệt tool: allowlist per-tool (mặc định PHẢI duyệt).
> Research nguồn: docs.stripe.com/mcp, scalar.com/learn/mcp/mcp-server-examples, awesome-mcp-servers,
> modelcontextprotocol/servers (+servers-archived), brave.com/search/api — kiểm chứng 2026-11.

## Đã có sẵn preset (18)

| # | Preset | Loại | Cách kết nối | Ghi chú |
|---|---|---|---|---|
| 1 | **github** | remote | `/connectors auth github <PAT>` | Endpoint chính thức api.githubcopilot.com (bản stdio `server-github` đã archived upstream) |
| 2 | **linear** | remote | API key hoặc OAuth | `mcp.linear.app/mcp` |
| 3 | **stripe** 🆕 | remote | `/connectors auth Stripe <rk_...>` | `mcp.stripe.com` — OAuth hoặc Bearer API key; khuyến nghị Restricted Key |
| 4 | **atlassian** 🆕 | remote | hub Composio (OAuth phía Atlassian) | `mcp.atlassian.com/v2/mcp` — Jira, Confluence |
| 5 | **vercel** 🆕 | remote | hub Composio (OAuth phía Vercel) | `mcp.vercel.com` — deployments, logs |
| 6 | **supabase** 🆕 | remote | hub Composio | `mcp.supabase.com/mcp` — mặc định read_only; DB riêng → preset postgres |
| 7 | **notion** | remote | OAuth 2.1 + PKCE engine tự chạy | `mcp.notion.com/mcp` |
| 8 | **sentry** | remote | OAuth 2.1 + PKCE engine tự chạy | `mcp.sentry.dev/mcp` |
| 9 | **context7** | remote | không cần key | docs thư viện lên-thời-đại |
| 10 | **figma-desktop** | local | Desktop app → Dev Mode MCP | thiết kế → code |
| 11 | **playwright** | stdio npx | không cần key | điều khiển browser (25 tool) |
| 12 | **filesystem** | stdio npx | `$FORGE_FS_DIR` | đọc/ghi ngoài workspace (không có undo của Forge!) |
| 13 | **postgres** | stdio npx | `$DATABASE_URL` | SQL CHỈ ĐỌC trên DB của bạn |
| 14 | **sequential-thinking** | stdio npx | không cần key | suy luận từng bước |
| 15 | **memory** 🆕 | stdio npx | không cần key | trí nhớ knowledge-graph (`memory.json`) |
| 16 | **fetch** 🆕 | stdio uvx | cần uv (`winget install astral-sh.uv`) | đọc web → markdown |
| 17 | **brave-search** 🆕 | stdio npx | `$BRAVE_API_KEY` (free 2k/tháng) | gói chính thức `@brave/brave-search-mcp-server` |
| 18 | **composio-hub** | remote hub | dán URL hub của bạn | 500+ app (Gmail, Google Drive/Sheets/Calendar, Slack…) |

## Cố tình KHÔNG thêm (lý do research)

| MCP | Lý do bỏ |
|---|---|
| `@modelcontextprotocol/server-github` (stdio) | **Archived upstream** — endpoint chính thức dời sang remote Copilot (đang dùng, mục 1) |
| `server-brave-search` (bản modelcontextprotocol) | **Archived** — Brave phát hành gói chính thức riêng `@brave/...` (đang dùng, mục 17) |
| Slack stdio (`server-slack`) | **Archived** — bản remote mcp.slack.com chỉ cho Enterprise; khuyên qua hub Composio |
| Git MCP (`mcp-server-git`) | Trùng checkpoints/worktree/autocommit sẵn có của Forge |
| Time MCP | Agent đã biết giờ theo hệ thống |
| Everything MCP | Server tham chiếu/test — không giá trị người dùng cuối |
| Puppeteer / SQLite / Redis / Google Drive stdio | Archived upstream hoặc cần service-account phức tạp (Google apps → hub) |
| browser-use / n8n / ComfyUI… | Third-party nặng, ngoài phạm vi agent lập trình |

## Nguyên tắc bảo mật khi thêm MCP ngoài danh sách

1. Ưu tiên **remote chính thức** của nhà cung cấp + OAuth; stdio thì pin gói đã kiểm chứng (`@modelcontextprotocol`, `@microsoft`, `@brave`, `@upstash`).
2. Dùng **Restricted/scope-tối-thiểu** key; mặc định read_only khi có lựa chọn.
3. Tool MCP mới luôn qua **allowlist approval** của Forge (mặc định PHẢI duyệt) — không tool nào chạy lặng.
