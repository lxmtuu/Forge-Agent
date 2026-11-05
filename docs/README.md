# 📚 Mục lục tài liệu Forge Agent

> Tất cả tài liệu dự án nằm trong `docs/`, chia 3 nhóm. File duy nhất giữ ở thư mục gốc là
> [README.md](../README.md) (chuẩn GitHub — trang chủ repo).

```
docs/
├── README.md      ← bạn đang ở đây (mục lục + quy ước)
├── assets/        ← ảnh/screenshot dùng trong README
├── guides/        ← hướng dẫn dùng & vận hành (đọc khi xài Forge)
├── research/      ← nghiên cứu kỹ thuật trước khi làm tính năng
└── reports/       ← báo cáo audit, đối chiếu, tổng kết (lưu lịch sử)
```

---

## 📖 guides/ — Hướng dẫn sử dụng & vận hành

| File | Nội dung | Dành cho |
|---|---|---|
| [QUICKSTART.md](guides/QUICKSTART.md) | Chạy Forge lần đầu trong 5 phút (Windows-first) | Người mới |
| [USER_GUIDE.md](guides/USER_GUIDE.md) | Hướng dẫn từng bước đầy đủ, tiếng Việt (11 mục + phụ lục lệnh) | Người dùng |
| [SECURITY.md](guides/SECURITY.md) | Mô hình account/signup, owner ACL, cookie/CSRF, OIDC, checklist | Operator |
| [DEPLOY.md](guides/DEPLOY.md) | Docker Compose, VPS + systemd + Caddy, Google login | Operator |
| [MCP_CATALOG.md](guides/MCP_CATALOG.md) | 18 preset MCP + nguyên tắc bảo mật khi thêm MCP | Người dùng |
| [BUILD_DESKTOP.md](guides/BUILD_DESKTOP.md) | Đóng gói TUI/EXE: `pip install`, PyInstaller, GitHub Release | Dev/operator |

Đọc theo thứ tự: QUICKSTART → USER_GUIDE → (SECURITY + DEPLOY nếu public server).

## 🔬 research/ — Nghiên cứu kỹ thuật

| File | Nội dung | Kết quả |
|---|---|---|
| [MULTI_MODEL.md](research/MULTI_MODEL.md) | Điều phối đa model: routing, alias, fallback (research Claude Code/Anthropic) | ✅ Đã triển khai v0.13 |
| [CONNECTORS_RESEARCH.md](research/CONNECTORS_RESEARCH.md) | Kết nối SaaS qua MCP remote + hub managed-OAuth | ✅ Đã triển khai v0.17–v0.21, v0.28–v0.29 |
| [SKILLS_RESEARCH.md](research/SKILLS_RESEARCH.md) | Chuẩn Agent Skills mở (Linux Foundation) & áp dụng vào Forge | ✅ Đã triển khai v0.11, v0.16, v0.26 |

## 📊 reports/ — Báo cáo audit, đối chiếu, tổng kết

> Nhóm này là **bản chụp lịch sử** — đọc để hiểu quá trình, không phải hướng dẫn hiện hành.
> Trạng thái mới nhất của từng hạng mục nằm ở cột ✅ **vX** trong PARITY/PROJECT_AUDIT.

| File | Nội dung | Trạng thái |
|---|---|---|
| [TONG_KET.md](reports/TONG_KET.md) | Tổng kết toàn dự án: lịch sử version, tính năng, kiểm thử, bàn giao | Hiện hành tới v0.38.0 |
| [PROJECT_AUDIT.md](reports/PROJECT_AUDIT.md) | Rà soát kỹ thuật từng vòng theo OWASP LLM + số liệu đo thật | Hiện hành (mỗi vòng 1 mục) |
| [PARITY.md](reports/PARITY.md) | Đối chiếu Forge vs Claude Code/Codex/OpenCode qua các version | Hiện hành (kế thừa FEATURE_AUDIT) |
| [FEATURE_AUDIT.md](reports/FEATURE_AUDIT.md) | Audit gốc 34 hạng mục chụp ở v0.6 | 📸 Snapshot — xem PARITY cho trạng thái mới |
| [GAP_ANALYSIS.md](reports/GAP_ANALYSIS.md) | Phân tích khoảng trống vs thị trường 2026 | ✅ Đóng hết backlog ở v0.32 (§2b) |
| [PRODUCT_DIRECTION.md](reports/PRODUCT_DIRECTION.md) | Định vị sản phẩm + lộ trình từ v0.6 | 📸 Snapshot — roadmap cũ, tham khảo |
| [AUDIT.md](reports/AUDIT.md) | Audit repo ngoài `cporter202/API-mega-list` (catalog Apify affiliate) | 📎 Tham khảo ngoài, không thuộc lõi Forge |

---

## ➕ Quy ước khi thêm tài liệu mới

1. **Hướng dẫn dùng/vận hành** → `docs/guides/`
2. **Nghiên cứu trước khi code** → `docs/research/`
3. **Báo cáo/audit/tổng kết theo đợt** → `docs/reports/`
4. Link liên file dùng **đường dẫn tương đối** (`../guides/…`, `../../README.md`).
5. Thêm 1 dòng vào bảng mục lục trên để người sau tìm được.
6. Không đặt thêm `.md` ở thư mục gốc (trừ `README.md`).
