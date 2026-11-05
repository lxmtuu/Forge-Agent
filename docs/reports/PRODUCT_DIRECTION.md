# 🧭 PRODUCT DIRECTION — Forge Agent v0.6+

> Nghiên cứu thị trường 10/2026: Claude Code 2.1, Cursor 3.5, OpenCode, Cline, Codex.
> Bài học rút ra + lộ trình của Forge.

## 1. Khảo sát đối thủ — ai có gì

| Tính năng | Claude Code | Cursor | OpenCode | Cline | **Forge hiện tại** |
|---|:-:|:-:|:-:|:-:|:-:|
| Agent loop (tools + tự sửa lỗi) | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Plan / Act split** (kế hoạch trước, duyệt rồi mới sửa) | ✅ | ✅ | ✅ Build/Plan | ✅ Plan/Act | ➖ chỉ approval từng lệnh |
| **Direct chat** (hỏi đáp không tool) | ✅ | ✅ | ✅ | ✅ | ➖ |
| **Battle/side-by-side model** | ➖ | ➖ | ➖ | ➖ | ➖ (chỉ LM Arena có ở mức chat) |
| MCP client | ✅ | ✅ | ✅ | ✅ | ✅ (stdio + HTTP) |
| Approval / human-in-the-loop | ✅ | ✅ | ✅ | ✅ "mọi hành vi" | ✅ guarded/ask/auto |
| Sub-agent song song | ✅ | ✅ Cloud Agents | ➖ | ➖ | ✅ |
| **AGENTS.md** (quy tắc dự án) | ✅ (CLAUDE.md tương thích) | ✅ | ✅ | ✅ | ➖ |
| **Làm việc với repo có sẵn** (mở thư mục dự án thật) | ✅ | ✅ | ✅ | ✅ | ➖ (workspace riêng từng phiên) |
| Git / GitHub (commit, PR) | ✅ qua CLI | ✅ Cloud Agent + Jira | ✅ | ✅ | ➖ (qua run_command) |
| Terminal tích hợp | ✅ (chính là terminal) | ✅ | ✅ | ✅ | ➖ (chỉ agent chạy lệnh) |
| Đa hình thái: CLI/TUI/Web | ✅ CLI+IDE | IDE | ✅ TUI+desktop | VS Code | ✅ TUI+Web+REPL |
| Model tùy ý (BYOK) | ➖ | ✅ | ✅ 75+ | ✅ | ✅ 450+ qua OpenRouter |

## 2. Định vị của Forge

**"OpenCode + LM Arena Battle, tự host 100%, BYOK qua OpenRouter."**
Điểm khác biệt không tool nào có: **Battle Mode cho coding agent** — cùng một nhiệm vụ
chạy đồng thời trên N model, mỗi model một workspace, xem side-by-side rồi chọn
phiên thắng cuộc để tiếp tục. Đây là tính năng viral/kiếm sao ⭐ tốt nhất.

## 3. v0.6 (bản này) — "Modes + Project + Terminal"

1. **4 chế độ làm việc**: 💬 Direct (chat thuần, không tool, nhanh/rẻ) ·
   🤖 Agent (vòng lặp đầy đủ) · 📋 Plan (chỉ đọc + xuất kế hoạch, không sửa gì —
   kế hoạch duyệt xong chuyển Agent thực thi) · ⚔ Battle (1 prompt → N model song song).
2. **Terminal tích hợp** trong web UI — Bạn gõ lệnh trực tiếp vào workspace
   (vẫn qua guard: guarded chặn danger).
3. **Mở dự án thật**: chỉ định thư mục bất kỳ làm workspace của phiên
   (bật bằng env `FORGE_ALLOW_OPEN=1` — mặc định tắt cho an toàn).
4. **AGENTS.md**: nếu workspace có file này, Forge đọc và tuân theo như quy tắc dự án.
5. Git qua terminal/agent: system prompt dạy quy tắc commit an toàn
   (chỉ stage phần mình sửa, không force-push nếu không được yêu cầu).

## 4. Lộ trình tiếp (ưu tiên)

- [ ] **v0.7 GitHub sâu**: tool `git_*` chuẩn (status/diff/commit/branch), tạo PR qua
  `gh` CLI, đọc issues; GitHub token lưu trong config
- [ ] **v0.7 Diff view**: render patch trước khi ghi file + nút accept/reject từng edit
- [ ] **v0.7 Battle nâng cao**: blind mode (ẩn tên model, vote xong mới lộ), vote lưu
  leaderboard cục bộ
- [ ] **v0.8 Context dài**: auto-compact hội thoại, tóm tắt phiên cũ khi vượt ngưỡng
- [ ] **v0.8 Hooks/skills**: file cấu hình chạy lệnh trước/sau tool (kiểu Claude Code hooks)
- [ ] **v0.9 Kênh thực thi đám mây**: chạy agent trong Docker per-session (isolation hoàn toàn)

## 5. Không làm (cố tình)

- Không làm IDE đầy đủ (đụng độ VS Code/Cursor) — Forge là agent, không phải editor.
- Không tự huấn luyện model hay tự host LLM — BYOK qua OpenRouter là đủ.
- Không cloud service có server trung gian — mọi thứ chạy trên máy người dùng.
