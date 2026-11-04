# ⚡ Forge Agent — AI Coding Agent tự host (kiểu Claude Code / Codex)

Forge là một coding agent **chạy trên máy bạn**: nó đọc/ghi/sửa file, tìm kiếm trong
codebase, chạy lệnh shell, tự kiểm chứng kết quả rồi tổng kết — y như Claude Code hay
Codex CLI, nhưng **bạn sở hữu toàn bộ** (engine + giao diện + dữ liệu).

Một engine duy nhất, **ba hình thái phần mềm** (chi tiết: BUILD_DESKTOP.md):

```
  forge            → TUI toàn màn hình trong terminal (kiểu OpenCode)
  forge --web      → Web UI (kiểu Claude Code web)
  forge --repl     → REPL dòng lệnh (kiểu Codex CLI)
  forge.exe        → file exe độc lập (build bằng PyInstaller/GitHub Actions)
```

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
| Hiển thị "suy nghĩ" (reasoning) | ✅ (dim stream) | ✅ (collapsible) |
| Tool cards: đọc/ghi/sửa file, search, chạy lệnh | ✅ | ✅ (collapsible) |
| Nhiều phiên (sessions) + workspace riêng từng phiên | ✅ | ✅ |
| **Sub-agent song song** (mỗi tác vụ 1 session + workspace) | ✅ `--parallel` | ✅ nút ⚡ Song song |
| **Upload file** vào workspace / **xuất zip** | — | ✅ (⬆ / ⤓) |
| **Đồng bộ 450+ model** từ OpenRouter (kèm giá/context) | ✅ `/model` | ✅ chip chọn model |
| **Theo dõi tokens/cost** theo phiên + toàn hệ thống | ✅ `/usage` | ✅ footer + Settings |
| Đổi model trực tiếp | ✅ `/model` | ✅ Settings |
| Demo mode (không cần API key) | ✅ `--demo` | ✅ tự kích hoạt |

**Tools có sẵn:** `list_dir` · `read_file` · `write_file` · `edit_file` ·
`search_files` (grep) · `run_command` (bash, timeout, giới hạn output) ·
**+ mọi tool từ MCP servers bên ngoài** (tự động namespace `mcp_<server>_<tool>`).

### 🎛 4 chế độ làm việc (v0.6)
| Chế độ | Hành vi |
|---|---|
| 💬 **Direct** | Chat thuần không tool — hỏi đáp nhanh, rẻ |
| 🤖 **Agent** | Vòng lặp đầy đủ: đọc/ghi file, chạy lệnh, tự sửa lỗi |
| 📋 **Plan** | Chỉ ĐỌC (list/read/search) + xuất kế hoạch chi tiết — không sửa gì; duyệt xong chuyển Agent thực thi (kiểu Cline/OpenCode Plan/Act) |
| ⚔ **Battle** | Cùng 1 prompt chạy song song trên tối đa 4 model, mỗi model 1 session+workspace, xem side-by-side rồi chọn phiên thắng cuộc (duy nhất ở Forge!) |

Kèm theo: **Terminal tích hợp** trong panel Files (bạn gõ lệnh chạy trực tiếp trong
workspace, vẫn qua guard), **AGENTS.md** (quy tắc dự án chuẩn Codex/OpenCode — đặt
file này vào workspace là agent tuân theo), và **mở dự án thật** làm workspace qua
`POST /api/workspace/open` (bật bằng env `FORGE_ALLOW_OPEN=1`).

### 🛋 Comfort (v0.7) — 5 lỗ hổng P0 trong FEATURE_AUDIT.md đã bị xóa sổ

| Tính năng | Web | TUI | CLI |
|---|---|---|---|
| **Diff view** — mỗi lần agent sửa file hiện diff xanh/đỏ + đếm ±dòng (kiểu PR) | ✅ tool card | — | — |
| **Checkpoints + Undo** — mọi write/edit/command tự chụp mốc git nội bộ; `↩ Undo` lùi workspace về mốc trước | ✅ nút | ✅ `/undo` | ✅ `/undo` |
| **/compact** — LLM tóm tắt hội thoại, giải phóng context | ✅ nút 🧹 | ✅ `/compact` | ✅ `/compact` |
| **Auto-compact** — phiên dài tự nén khi vượt ngưỡng (env `FORGE_AUTO_COMPACT`, mặc định 150000 ký tự, 0 = tắt) | ✅ | ✅ | ✅ |
| **/init** — phân tích workspace, sinh `AGENTS.md` (demo-mode khi chưa có key) | ✅ nút 🚀 | ✅ `/init` | ✅ `/init` |
| **TUI đổi chế độ chat** — `Ctrl+M` xoay vòng 🤖 agent / 📋 plan / 💬 direct | — | ✅ | ✅ `--mode` |
| Quy tắc dự án: `AGENTS.md` > `AGENTS.txt` > `CLAUDE.md` (fallback Claude Code) + global `data/AGENTS.md` | ✅ | ✅ | ✅ |

*Ghi chú Undo:* checkpoint nằm trong git-inner repo riêng `data/workspaces/.ckpt-*.git`
— không bao giờ đụng `.git` của dự án thật. Undo lùi đúng **1 hành động của agent**
(mỗi write/edit/command là 1 mốc); file sinh ra sau mốc sẽ bị xóa khi lùi qua mốc đó
(đúng ngữ nghĩa undo). Tắt bằng `checkpoints_enabled: false` trong `data/config.json`.

CLI/TUI: `forge --battle "prompt" --models m1 m2 m3` · `forge --once "..." --mode plan`.

Định hướng sản phẩm chi tiết: **PRODUCT_DIRECTION.md**.

Mọi đường dẫn file bị chặn thoát khỏi workspace của phiên; lệnh shell chạy với
timeout 30s (tối đa 120s) và output bị cắt ở 12k ký tự.

### 🛡 An toàn lệnh shell — 3 chế độ
- **Guarded** (mặc định): phân loại lệnh safe/warn/danger — lệnh nguy hiểm
  (`sudo`, `rm -rf /`, `curl | bash`…) bị **chặn** sẵn, agent phải giải thích.
- **🔔 Hỏi từng lệnh (ask)**: agent tạm dừng, hiện thẻ phê duyệt với lệnh + lý do;
  bạn chọn **Chấp nhận / Luôn cho phép lệnh này / Từ chối** (web hoặc terminal).
  Lệnh được "luôn cho phép" lưu vào phiên, lần sau không hỏi lại. Timeout 3 phút = tự từ chối.
- **Auto (YOLO)**: chạy mọi lệnh, rủi ro tự chịu.
- **Docker sandbox**: nếu máy có Docker, bật trong Settings để mọi lệnh chạy
  trong container `--network=none --memory=512m --cpus=1 --cap-drop=ALL`.

### 🔌 MCP client (mới)
Kết nối MCP server chuẩn (stdio JSON-RPC) — agent tự nhận thêm tool:
1. ⚙ Settings → MCP servers → thêm, VD server filesystem:
   `npx` + args `-y, @modelcontextprotocol/server-filesystem, /tmp/du-lieu`
2. Lưu lại → từ lượt chat kế tiếp, model thấy tool `mcp_fs_*` và dùng như tool thường.
3. Test nhanh có sẵn: `python3 scripts/demo_mcp_server.py` (echo/add/now_time),
   cấu hình mẫu trong `mcp.example.json`.
4. Trong CLI: `/mcp` xem trạng thái, `/mcp refresh` khởi động lại.

Hỗ trợ **2 transport**: `stdio` (subprocess) và **`http`** (Streamable-HTTP với
`Mcp-Session-Id`) — ví dụ trong `mcp.example.json`, server test HTTP:
`python -m uvicorn scripts.demo_mcp_http_server:app --port 8931`.

### ⚡ Sub-agent song song (mới)
Chạy nhiều tác vụ đồng thời, mỗi tác vụ một session + workspace riêng biệt:
```bash
# CLI
python cli/main.py --parallel "viết fizzbuzz" "tạo README" "viết hàm sqrt + test"
```
Web: bấm nút **⚡ Song song** cạnh ô nhập → mỗi dòng trở thành 1 tác vụ → Gửi.
Kết quả hiển thị theo nhóm Task 1/2/3… với trạng thái riêng từng task.

### 🔢 Theo dõi usage + đồng bộ model (mới)
- Tokens/cost tích luỹ theo phiên (CLI `/usage`, web footer) và toàn hệ thống (Settings).
- Danh sách model **tự đồng bộ từ OpenRouter** mỗi giờ — chọn model bằng chip có
  sẵn giá ($/M tokens) và context length.

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

### CLI / TUI
```bash
pip install -e .              # cài 1 lần → có lệnh `forge` trong PATH
forge                         # TUI toàn màn hình (khuyên dùng — kiểu OpenCode)
forge --repl                  # REPL đơn giản
forge --once "viết fizzbuzz rồi chạy test"
forge --parallel "task A" "task B"
forge --list-sessions
# hoặc không cài: python cli/main.py / python -m tui.launch
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
- [x] Tải file lên workspace, xuất zip
- [x] Sub-agent / chạy song song nhiều tác vụ
- [x] Đồng bộ model list tự động từ `openrouter.ai/api/v1/models` + theo dõi tokens
- [x] MCP transport HTTP (streamable, `Mcp-Session-Id`) — song song với stdio
- [x] Duyệt lệnh tương tác: chế độ **ask** hiện thẻ phê duyệt trước khi chạy lệnh warn/danger

---
*Được xây kèm audit của repo `cporter202/API-mega-list` — xem `AUDIT.md` để hiểu
bối cảnh và bài học thiết kế rút ra.*
