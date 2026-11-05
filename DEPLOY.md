# 🚀 DEPLOY — Forge Agent v0.35 account & access

> Đọc **SECURITY.md** trước. Một process/VPS, account do admin tạo hoặc public signup opt-in, owner ACL cho session/workspace. Provider key và Auth DB chỉ nằm ở persistent data, không trong git/image/ZIP.

## 1. Docker Compose

```bash
git clone <repo-cua-ban> forge-agent && cd forge-agent
docker compose build

# Nhập key ẩn; nếu chưa có user, tạo luôn admin đầu tiên.
docker compose run --rm forge python scripts/setup_keys.py --provider openrouter --release
# Google Gemini: thay --provider google

# Hoặc tạo/thêm user riêng (password nhập ẩn):
docker compose run --rm forge python scripts/setup_auth.py --email admin@example.com --role admin

docker compose up -d
docker compose exec forge python scripts/setup_keys.py --check
docker compose exec forge python scripts/setup_auth.py --check
```

Compose chỉ publish `127.0.0.1:8000`. `./data` là persistent volume chứa provider key, `auth.db`, sessions và workspaces; giữ volume này khi update. Không đặt secret trong `docker-compose.yml` hoặc build args.

Khi đã có HTTPS domain, cấu hình `FORGE_PUBLIC_URL=https://forge.example.com` hoặc `FORGE_COOKIE_SECURE=1` cho runtime container. Nếu bật Google login, cấu hình public URL trong Team để cookie Secure và redirect URI đúng.

Update code:

```bash
git pull
docker compose build
docker compose up -d
# Giữ ./data; chạy lại cả hai --check và smoke login.
```

## 2. VPS trần — systemd + Caddy

### 2.1 Code, dependencies và data

```bash
sudo mkdir -p /opt/forge-agent
# Copy/clone release vào /opt/forge-agent rồi:
cd /opt/forge-agent
sudo python3 -m pip install -r requirements.txt
sudo install -d -o www-data -g www-data -m 700 /var/lib/forge

# Nhập key và tạo admin dưới đúng OS user runtime.
sudo -u www-data env FORGE_DATA_DIR=/var/lib/forge \
  python3 scripts/setup_keys.py --provider google --release
# OpenRouter: --provider openrouter
```

### 2.2 systemd unit — không chứa secret

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
Environment=FORGE_PUBLIC_URL=https://forge.example.com
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
```

Nếu cần mở project ngoài `/var/lib/forge`, phải bổ sung `ReadWritePaths` và quyền OS một cách có chủ đích. Không tắt hardening chỉ để “cho tiện”.

### 2.3 HTTPS reverse proxy

```caddy
forge.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo systemctl reload caddy
curl https://forge.example.com/api/health
```

Không cần nhân đôi Basic Auth ở proxy. Giữ Forge cookie auth; Nginx phải tắt buffering cho SSE (`proxy_buffering off`, `proxy_read_timeout 600`).

## 3. Google login (tuỳ chọn)

Trong Google Cloud, tạo OAuth **Web application** và đăng ký:

```text
https://forge.example.com/api/auth/google/callback
```

Sau đó admin vào **⚙ → Team → Google OpenID Connect**, hoặc chạy:

```bash
sudo -u www-data env FORGE_DATA_DIR=/var/lib/forge \
  python3 /opt/forge-agent/scripts/setup_auth.py --google \
  --client-id '<oauth-client-id>' --public-url 'https://forge.example.com'
```

Client secret nhập ẩn. Scope chỉ `openid email profile`; không phải Gmail/Drive OAuth. Khi public signup tắt, user Google-only phải được admin tạo trước bằng đúng email. Nếu admin bật public signup, Google user mới cũng chỉ được tạo làm member.

### 3.1 Public signup (tuỳ chọn, mặc định tắt)

Admin bật trong **⚙ → Team → Cho phép tự đăng ký tài khoản member**. Có thể đặt `FORGE_ALLOW_REGISTRATION=1` làm default ban đầu cho deployment mới; lựa chọn admin trong Auth DB sau đó được ưu tiên.

Public signup chỉ tạo member, yêu cầu CSRF/password ≥16 ký tự và có rate-limit theo IP/email. **Chưa có SMTP email verification**; production public Internet nên đặt gateway quota + CAPTCHA phía trước và theo dõi user mới. Không expose uvicorn trực tiếp. Kiểm tra `setup_auth.py --check` để xem policy hiện tại.

## 4. PaaS có persistent disk

Render/Railway/Fly.io phù hợp hơn nền tảng serverless vì Forge cần Python process lâu dài, SQLite và SSE.

- Build: `pip install -r requirements.txt` hoặc Docker image (Web static đã có sẵn).
- Start: `python -m uvicorn server.main:app --host 0.0.0.0 --port $PORT` trong private runtime, public qua HTTPS nền tảng.
- Mount persistent disk và đặt `FORGE_DATA_DIR` tới disk đó. **Auth DB cũng cần persist**, không chỉ provider config.
- Đặt `FORGE_RELEASE_MODE=1`, `FORGE_PUBLIC_URL=https://...`; provider key có thể đến từ secret manager (`OPENROUTER_API_KEY`/`GOOGLE_API_KEY`).
- Chạy `setup_auth.py` để tạo admin trước khi mở traffic. Không dùng `FORGE_ADMIN_TOKEN`/shared password legacy thay cho user thật.
- Rate limit trong app là per-process; cấu hình quota tổng ở gateway nếu scale.

## 5. Nâng cấp từ v0.33

1. Backup toàn bộ data.
2. Cài code/dependencies mới (`authlib` là dependency bắt buộc).
3. Tạo admin bằng `setup_auth.py` nếu Auth DB chưa có user.
4. Session cũ `owner_id=""` sẽ bị ẩn; dry-run migration:

   ```bash
   python scripts/migrate_sessions.py --email admin@example.com
   ```

5. Kiểm tra danh sách rồi mới áp dụng:

   ```bash
   python scripts/migrate_sessions.py --email admin@example.com --apply
   ```

6. Chạy `test_v033.py`, `test_v034.py`, `--check` và HTTP/browser smoke trước khi mở traffic.

## 6. Checklist public

| Việc | Kết quả bắt buộc |
|---|---|
| Provider + users | Cả hai `--check` exit 0; có ít nhất một admin active |
| Anonymous | Login/static + health public; `/api/sessions` trả 401 |
| Cookie/CSRF | Session HttpOnly + Secure qua HTTPS; mutation thiếu CSRF trả 403 |
| Owner ACL | User A không đọc/thao tác session/workspace của user B |
| Release settings | Member không đổi global settings; release key settings chỉ qua terminal |
| HTTPS/CORS | Backend không expose trực tiếp; không dùng CORS `*` ở release |
| Quota | Rate limit phù hợp; proxy có quota tổng nếu nhiều worker |
| MCP/skills | Member không dùng credential MCP toàn server hoặc sửa global skill |
| Secret | `data/`, `.env`, Auth DB/provider secret không trong git/image/ZIP/log |
| OAuth thật | Nếu bật Google: consent/callback/logout/re-login và uninvited flow đã smoke |

## 7. Runtime layout

```text
data/                              # hoặc /var/lib/forge
├── config.json                    # model/provider/policy — không provider key
├── provider-secrets.json          # OpenRouter/Google/custom key (0600)
├── auth.db                        # users, password/session hash, OIDC config
├── secrets.json                   # connector token nếu dùng
├── mcp.json                       # cấu hình MCP; có thể chứa secret explicit
├── sessions/                      # hội thoại JSON có owner_id
├── workspaces/
└── session-migration-backup/      # backup khi chạy migration --apply
```
