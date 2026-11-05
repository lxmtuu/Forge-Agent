# 🚀 DEPLOY — một Forge server dùng chung, không nhúng key vào release

> Đọc **SECURITY.md** trước. Mô hình này dành cho nhóm tin cậy, không phải multi-tenant isolation. Provider key do operator nhập trong terminal; release ZIP/image không chứa key hay password.

## Cách 1: Docker Compose (khuyên dùng)

```bash
git clone <repo-cua-ban> forge-agent && cd forge-agent

docker compose build
# Terminal tương tác: nhập key ẩn + release password; ghi vào volume ./data
docker compose run --rm forge python scripts/setup_keys.py --provider openrouter --release
# Google: thay openrouter bằng google

docker compose up -d
python scripts/setup_keys.py --check   # nếu chạy trên host cùng FORGE_DATA_DIR
# Hoặc kiểm tra trong container:
docker compose exec forge python scripts/setup_keys.py --check
```

Mặc định compose chỉ publish **`127.0.0.1:8000`**. Đưa domain HTTPS tới port đó bằng Caddy/Nginx; không đổi thành `0.0.0.0`/public port khi chưa có proxy.

Cập nhật code mà giữ data/secret:

```bash
git pull
docker compose build
docker compose up -d
# ./data được giữ nguyên; chạy --check sau update
```

## Cách 2: VPS trần (systemd + Caddy HTTPS)

### 1. Code, dependencies và data ngoài source

```bash
sudo mkdir -p /opt/forge-agent
# Copy/clone release vào /opt/forge-agent rồi:
cd /opt/forge-agent
sudo python3 -m pip install -r requirements.txt
sudo install -d -o www-data -g www-data /var/lib/forge

# Nhập key ẩn dưới đúng user runtime; KHÔNG ghi key vào unit file.
sudo -u www-data env FORGE_DATA_DIR=/var/lib/forge \
  python3 scripts/setup_keys.py --provider google --release
# OpenRouter: --provider openrouter
```

### 2. systemd unit — không có secret trong file

```bash
sudo tee /etc/systemd/system/forge.service <<'EOF'
[Unit]
Description=Forge Agent
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/forge-agent
Environment=FORGE_DATA_DIR=/var/lib/forge
Environment=FORGE_RELEASE_MODE=1
Environment=FORGE_RATE_LIMIT_PER_MIN=20
ExecStart=/usr/bin/python3 -m uvicorn server.main:app --host 127.0.0.1 --port 8000
Restart=always
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/var/lib/forge

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now forge
sudo -u www-data env FORGE_DATA_DIR=/var/lib/forge \
  python3 /opt/forge-agent/scripts/setup_keys.py --check
```

Nếu cần mở project ngoài `/var/lib/forge`, phải điều chỉnh `ReadWritePaths` và quyền OS một cách có chủ đích; không tắt hardening chỉ để “cho tiện”.

### 3. HTTPS qua Caddy

```caddy
forge.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo systemctl reload caddy
```

Forge release đã có Basic/Bearer auth; không cần nhân đôi basic-auth ở Caddy. Có thể dùng SSO gateway ngoài nếu muốn, nhưng vẫn giữ auth của Forge. Nginx: `proxy_buffering off; proxy_read_timeout 600;` để SSE hoạt động.

## Cách 3: PaaS có persistent disk

Render/Railway/Fly.io phù hợp hơn Vercel/Netlify vì Forge cần process Python lâu dài và SSE.

- Build: `pip install -r requirements.txt` (dùng Web static có sẵn) hoặc build Docker image.
- Start: `python -m uvicorn server.main:app --host 0.0.0.0 --port $PORT` trong private runtime, public qua HTTPS của nền tảng.
- Mount disk và đặt `FORGE_DATA_DIR` tới disk đó; chạy terminal setup một lần trước khi mở traffic.
- Nếu nền tảng không có terminal/persistent disk, dùng **secret manager** cho `OPENROUTER_API_KEY` hoặc `GOOGLE_API_KEY`, `FORGE_ADMIN_TOKEN`, đặt `FORGE_RELEASE_MODE=1`. Không dán secret vào build args/source/log.
- Rate limit trong app là per-process; cấu hình quota tổng ở gateway khi chạy nhiều instance.

## 🔐 Checklist trước khi public

| Việc | Kết quả bắt buộc |
|---|---|
| Terminal setup | Provider credentials + release auth đều sẵn sàng, `--check` exit 0 |
| Auth | Không credentials → 401; thiếu auth setup → 503; Settings/keycheck khi release → 403 |
| HTTPS | Basic/Bearer chỉ đi qua HTTPS; backend không expose trực tiếp |
| CORS | Same-origin mặc định; tuyệt đối không `*` ở release |
| Quota | Giữ `FORGE_RATE_LIMIT_PER_MIN` phù hợp; proxy có giới hạn tổng nếu nhiều worker |
| Shell | `approval_mode=guarded`; cân nhắc Docker/container sandbox |
| Secret | `data/`, `.env`, provider/auth file không nằm trong git/image/ZIP; log không chứa full secret |
| Trust boundary | Chỉ cấp login cho nhóm tin cậy; session/workspace không cô lập giữa người dùng |

## Cấu trúc dữ liệu runtime

```text
data/                              # hoặc /var/lib/forge
├── config.json                    # provider/model/policy — không provider key
├── provider-secrets.json          # key OpenRouter/Google/custom (0600)
├── release-auth.json              # salt + PBKDF2 hash, không password thô
├── secrets.json                   # connector OAuth/token (nếu dùng connectors)
├── mcp.json                       # cấu hình MCP; coi là secret nếu có env explicit
├── sessions/                      # hội thoại JSON
└── workspaces/                    # workspace từng phiên
```
