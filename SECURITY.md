# 🔐 SECURITY — vận hành Forge Agent cho một server dùng chung

> Áp dụng từ **v0.33.0**. Mô hình mục tiêu: **một server, operator giữ provider key, nhóm tin cậy dùng chung**. Đây không phải hệ thống multi-tenant cô lập: người có tài khoản release có thể xem session/workspace của nhau và yêu cầu agent chạy tool theo policy của server.

## 1. Chuẩn bị key trong terminal — trước khi phát hành

Không dán key vào chat, source, `Dockerfile`, `docker-compose.yml`, Web bundle hay ZIP. Chạy trong terminal tương tác trên server:

```bash
# OpenRouter
python scripts/setup_keys.py --provider openrouter --release

# Hoặc Google Gemini (OpenAI-compatible endpoint)
python scripts/setup_keys.py --provider google --release

# Hoặc server OpenAI-compatible/Ollama
python scripts/setup_keys.py --provider custom --release

# Chỉ kiểm tra trạng thái (không sửa, không in full key)
python scripts/setup_keys.py --check
```

Cách tương đương qua launcher:

```bash
python scripts/launch.py --setup --provider google --release
python scripts/launch.py --release --no-browser
```

- Key/password được nhập bằng `getpass` (không echo); setup từ chối stdin không tương tác.
- Không có tùy chọn `--key`, tránh key nằm trong shell history/process list.
- Release password: username cố định **`forge`**, mật khẩu tối thiểu **16 ký tự**; chỉ salt + PBKDF2-HMAC-SHA256 hash (240.000 vòng) được lưu.
- Operator nên dùng `FORGE_DATA_DIR` ngoài cây source trên production. Ví dụ: `/var/lib/forge`.

### Nơi lưu runtime

```text
$FORGE_DATA_DIR/
├── config.json             # provider/model/policy, KHÔNG chứa provider key
├── provider-secrets.json   # openrouter/google/custom key, chmod 600 khi hỗ trợ
├── release-auth.json       # username + salt + PBKDF2 hash, KHÔNG password thô
├── sessions/
└── workspaces/
```

`data/` đã bị gitignore và bị loại khỏi artifact phát hành. Key được đọc theo thứ tự **environment → provider-secrets.json → legacy config**; lần lưu config kế tiếp migrate legacy key ra secret file. Environment vẫn là lựa chọn cho secret manager của nền tảng, nhưng không phải mặc định an toàn tuyệt đối (process dump/log của hạ tầng có thể ghi env).

## 2. Release mode làm gì

Khi `release_mode=true` hoặc `FORGE_RELEASE_MODE=1`:

- Toàn bộ Web/API/static yêu cầu **Basic auth** (`forge` + release password) hoặc **Bearer** (password/`FORGE_ADMIN_TOKEN`).
- Thiếu cấu hình auth → **503 fail-closed**; thiếu/sai credentials → **401**.
- `POST /api/settings` và `/api/keycheck` → **403**; Web hiển thị trạng thái mask và hướng dẫn terminal, nút Lưu bị khóa.
- CORS mặc định **same-origin**; không còn wildcard. Đặt `FORGE_CORS_ORIGINS=*` ở release làm server từ chối khởi động.
- Request LLM (`chat`, `compact`, `init`, `loop`, `batch`, `battle`) bị giới hạn mặc định **20 request/phút/user+IP**; đổi bằng `FORGE_RATE_LIMIT_PER_MIN` (1–1000). Response giới hạn là **429 + Retry-After**.
- Có rate-limit đăng nhập sai theo IP. Cache API `no-store`, thêm `nosniff` và `Referrer-Policy: no-referrer`.

Rate limit hiện là **in-process**. Nếu chạy nhiều worker/instance, cần giới hạn tổng ở reverse proxy/API gateway; không dùng số liệu per-process như quota toàn cụm.

### CORS có chủ đích (chỉ khi thật sự cần)

```bash
FORGE_CORS_ORIGINS=https://forge.example.com
```

Chỉ liệt kê origin HTTPS chính xác, phân tách nhiều origin bằng dấu phẩy. Không dùng `*`; khởi động lại server sau khi đổi.

## 3. HTTPS và reverse proxy là bắt buộc khi qua mạng

Basic/Bearer credentials chỉ được bảo vệ khỏi nghe lén khi đi qua **HTTPS**. Chạy uvicorn sau Caddy/Nginx/SSO gateway và chỉ bind loopback khi proxy cùng máy. Ví dụ Caddy:

```caddy
forge.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Nginx cần giữ SSE: `proxy_buffering off; proxy_read_timeout 600;`. Không mở trực tiếp port uvicorn ra Internet. Xem **DEPLOY.md** cho systemd/Docker đầy đủ.

## 4. Boundary của provider key và subprocess

- Shell, hook, background task, git/checkpoint/worktree, review, LSP và skill manager dùng environment đã loại `OPENROUTER_API_KEY`, `GOOGLE_API_KEY`, `GEMINI_API_KEY`, `FORGE_CUSTOM_API_KEY`, `FORGE_ADMIN_TOKEN` và các LLM credential liên quan.
- MCP stdio mặc định **không** nhận các key đó. Chỉ secret được khai báo explicit trong `env` của từng MCP server mới được truyền; opt-in một key không mở toàn bộ secret khác.
- Không cấp provider key cho MCP nếu MCP không thật sự cần. Nếu khai báo secret trong `data/mcp.json`, file đó cũng phải được coi là secret store, giữ ngoài git/ZIP và hạn chế quyền đọc.
- Provider error body được redact Authorization/API key trước khi đưa vào SSE/log. Health chỉ trả bản mask, không trả full secret; Web không lưu credential vào browser storage.

Các secret khác như `DATABASE_URL`/connector token có thể là opt-in riêng cho connector. Chỉ cài MCP/hook đáng tin: chúng là code chạy trên server.

## 5. Checklist trước khi mở cho nhóm

1. `python scripts/setup_keys.py --provider <openrouter|google|custom> --release` thành công.
2. `python scripts/setup_keys.py --check` exit 0, chỉ hiện key mask.
3. Chạy một process/worker trước khi cần scale; bật rate-limit tổng ở proxy nếu scale.
4. HTTPS hoạt động; port backend chỉ listen loopback/private network.
5. Không có `FORGE_CORS_ORIGINS=*`; ưu tiên không cấu hình CORS.
6. Giữ `approval_mode=guarded`; cân nhắc `docker_sandbox` và container riêng.
7. `git status --ignored` / kiểm tra ZIP không có `data/`, `provider-secrets.json`, `release-auth.json`, `.env`.
8. Đăng nhập thử, xác nhận Settings khóa; thử request không auth phải 401 (hoặc 503 nếu chưa setup auth).
9. Theo dõi chi phí/quota tại provider. Google Free Tier có thể dùng dữ liệu để cải thiện sản phẩm — không gửi code bí mật lên Free Tier.
10. Người dùng phải thuộc nhóm tin cậy; không coi đây là isolation giữa khách hàng lạ.

## 6. Đổi/thu hồi key hoặc password

1. Dừng traffic/server.
2. Chạy lại `python scripts/setup_keys.py --provider <provider> --release`; nhập key mới và/hoặc password mới.
3. Khởi động lại và chạy `--check`.
4. Thu hồi key cũ tại OpenRouter/Google. Xóa bản secret cũ khỏi backup không cần thiết theo policy của operator.

Không xóa `release-auth.json` khi server đang public: lần request kế tiếp sẽ fail-closed 503, nhưng đây là khóa khẩn cấp chứ không phải quy trình rotation bình thường.

## 7. Regression test

```bash
python scripts/test_v033.py
```

Suite dùng fake key và `FORGE_DATA_DIR` tạm; không gọi provider thật. Phạm vi: secret migration, PBKDF2, Google/OpenRouter/custom, shell/hook/background/git/MCP env, release auth, Settings lock, CORS/preflight, rate-limit, terminal setup, API/Web redaction.
