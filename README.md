# ⚡ Forge Agent — AI Coding Agent tự host (kiểu Claude Code / Codex)

Forge là một coding agent **chạy trên máy bạn**: nó đọc/ghi/sửa file, tìm kiếm trong
codebase, chạy lệnh shell, tự kiểm chứng kết quả rồi tổng kết — y như Claude Code hay
Codex CLI, nhưng **bạn sở hữu toàn bộ** (engine + giao diện + dữ liệu).

Một engine duy nhất, hai giao diện:

```
                    ┌─────────────────────────┐
   OpenRouter API   │      forge engine       │
◄──────────────────►│  agent loop + tools     │
  (Claude/GPT/...)  │  sessions + workspace   │
                    └───────────┬─────────────┘
              ┌─────────────────┼──────────────────┐
              ▼                                    ▼
      cli/main.py (Rich TUI)              server/main.py (FastAPI)
      → dùng như Codex CLI                → SSE streaming + REST
                                           → web/ React UI (như Claude Code web)
```

## ✨ Tính năng (v1)

| Tính năng | CLI | Web |
|---|:-:|:-:|
| Streaming token-by-token | ✅ | ✅ |
| Hiển thị "suy nghĩ" (reasoning) | — | ✅ (collapsible) |
| Tool cards: đọc/ghi/sửa file, search, chạy lệnh | ✅ | ✅ (collapsible) |
| Nhiều phiên (sessions) + workspace riêng từng phiên | ✅ | ✅ |
| File explorer + trình soạn thảo | ✅ (lệnh) | ✅ (GUI) |
| Đổi model trực tiếp | ✅ `/model` | ✅ Settings |
| Demo mode (không cần API key) | ✅ `--demo` | ✅ tự kích hoạt |

**Tools có sẵn:** `list_dir` · `read_file` · `write_file` · `edit_file` ·
`search_files` (grep) · `run_command` (bash, timeout, giới hạn output) ·
**+ mọi tool từ MCP servers bên ngoài** (tự động namespace `mcp_<server>_<tool>`).

Mọi đường dẫn file bị chặn thoát khỏi workspace của phiên; lệnh shell chạy với
timeout 30s (tối đa 120s) và output bị cắt ở 12k ký tự.

### 🛡 An toàn lệnh shell (mới)
- **Guarded mode** (mặc định): phân loại lệnh thành safe/warn/danger —
  lệnh nguy hiểm (`sudo`, `rm -rf /`, `curl | bash`…) bị **chặn** và agent phải
  giải thích cho người dùng thay vì chạy lén.
- **Auto (YOLO)**: chạy mọi lệnh, bật trong Settings khi bạn chấp nhận rủi ro.
- **Docker sandbox**: nếu máy có Docker, bật trong Settings để mọi lệnh chạy
  trong container `--network=none --memory=512m --cpus=1 --cap-drop=ALL`.

### 🔌 MCP client (mới)
Kết nối MCP server chuẩn (stdio JSON-RPC) — agent tự nhận thêm tool:
1. ⚙ Settings → MCP servers → thêm, VD server filesystem:
   `npx` + args `-y, @modelcontextprotocol/server-filesystem, /tmp/du-lieu`
2. Lưu lại → từ lượt chat kế tiếp, model thấy tool `mcp_fs_*` và dùng như tool内置.
3. Test nhanh có sẵn: `python3 scripts/demo_mcp_server.py` (echo/add/now_time),
   cấu hình mẫu trong `mcp.example.json`.

## 🚀 Chạy

### Web
```bash
pip install -r requirements.txt
cd web && npm install && npm run build && cd ..   # build 1 lần
uvicorn server.main:app --host 0.0.0.0 --port 8000
# mở http://localhost:8000
# hoặc: ./run.sh  (tự cài + tự build + chạy)
# hoặc: docker compose up -d --build
```
Deploy VPS/PaaS chi tiết: **DEPLOY.md**.

### CLI
```bash
python cli/main.py                        # REPL tương tác
python cli/main.py --once "viết fizzbuzz bằng python rồi chạy test"
python cli/main.py --list-sessions
python cli/main.py --session <id>         # quay lại phiên cũ
```

### API key (OpenRouter)
- Cách 1: `export OPENROUTER_API_KEY=sk-or-v1-...`
- Cách 2: nhập trong Web UI (⚙ Settings) hoặc gõ `/key sk-or-...` trong CLI.
  Key lưu ở `data/config.json` (chmod 600), chỉ gửi thẳng tới OpenRouter.

Lấy key miễn phí tại **https://openrouter.ai/keys** — một key dùng được cho
Claude, GPT, Gemini, DeepSeek, Qwen, Kimi… (model mã hoá `provider/model`).

Model mặc định: `anthropic/claude-sonnet-5.5`. Đổi tuỳ thích trong Settings.
Model rẻ để test: `google/gemini-3.8-flash` hoặc `deepseek/deepseek-v4.1-flash`.

## 🏗️ Kiến trúc

```
forge-agent/
├── engine/               # lõi dùng chung — không phụ thuộc UI
│   ├── agent.py          # vòng lặp: LLM → tool_calls → thực thi → lặp (tối đa 30 vòng)
│   ├── llm.py            # OpenRouter SSE streaming, tích luỹ tool_calls từng delta
│   ├── tools.py          # 6 tool + schema OpenAI + sandbox đường dẫn/timeout
│   ├── guard.py          # phân loại lệnh shell + Docker sandbox wrapper
│   ├── mcp.py            # MCP client (stdio JSON-RPC) + manager
│   ├── session.py        # phiên JSON: messages chuẩn OpenAI, workspace riêng
│   └── config.py         # key/model, approval mode, thư mục data/
├── server/main.py        # FastAPI: /api/... + /api/mcp + static web build
├── cli/main.py           # Rich TUI, chạy chung engine
├── web/                  # React + Vite + TypeScript (không dùng UI framework)
├── scripts/demo_mcp_server.py  # MCP server mẫu để test
├── Dockerfile / docker-compose.yml / DEPLOY.md
└── data/                 # runtime: sessions/, workspaces/, config.json, mcp.json
```

Sự kiện engine phát ra (CLI và web cùng tiêu thụ):
`reasoning_delta` · `assistant_delta` · `tool_start` · `tool_result` ·
`assistant_message` · `error` · `turn_end`.

## 🔐 Bảo mật — đọc trước khi exposing ra internet

- **Guarded mode** chặn sẵn các lệnh nguy hiểm nhất; bật **docker_sandbox** khi có
  Docker để cách ly hoàn toàn (không mạng, giới hạn tài nguyên).
- Public server? Đặt sau reverse-proxy **có auth** — checklist đầy đủ trong DEPLOY.md.
- API key không bao giờ gửi về browser (chỉ trả bản đã mask), lưu chmod 600.
- Session/workspace đặt tên file an toàn (sanitize), đường dẫn bị chặn thoát root.

## 🗺️ Roadmap gợi ý

- [x] Guard phân loại lệnh + chế độ guarded/auto (giống approval mode của Codex)
- [x] Docker sandbox wrapper (tự kích hoạt khi có Docker)
- [x] MCP client — nối tool server bên ngoài (hệ sinh thái MCP)
- [x] Đóng gói deploy: Dockerfile + compose + DEPLOY.md (VPS/PaaS)
- [ ] Tải file lên workspace, xuất zip
- [ ] Sub-agent / chạy song song nhiều tác vụ
- [ ] Đồng bộ model list tự động từ `openrouter.ai/api/v1/models`
- [ ] MCP transport HTTP/SSE (hiện hỗ trợ stdio)

---
*Được xây kèm audit của repo `cporter202/API-mega-list` — xem `AUDIT.md` để hiểu
bối cảnh và bài học thiết kế rút ra.*
