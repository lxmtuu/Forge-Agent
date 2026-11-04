# 🚀 DEPLOY — đưa Forge Agent lên server

## Cách 1: Docker Compose (khuyên dùng — VPS bất kỳ)

```bash
git clone <repo-của-bạn> forge-agent && cd forge-agent
export OPENROUTER_API_KEY=sk-or-v1-...        # hoặc để trống rồi nhập trong UI
docker compose up -d --build
# → http://IP-SERVER:8000
```

Cập nhật: `git pull && docker compose up -d --build`.

## Cách 2: VPS trần (systemd + Caddy HTTPS)

```bash
# 1. code + deps
git clone <repo> forge-agent && cd forge-agent
pip install -r requirements.txt
(cd web && npm ci && npm run build)           # hoặc dùng bản static đã build sẵn

# 2. systemd unit
sudo tee /etc/systemd/system/forge.service <<'EOF'
[Unit]
Description=Forge Agent
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/forge-agent
Environment=OPENROUTER_API_KEY=sk-or-v1-...
ExecStart=/usr/bin/python3 -m uvicorn server.main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now forge

# 3. HTTPS qua Caddy (domain example.com)
sudo tee /etc/caddy/Caddyfile <<'EOF'
forge.example.com {
    reverse_proxy 127.0.0.1:8000
    # khuyến nghị thêm basic_auth khi để công khai:
    # basic_auth { user $2a$14$HASH_BẠN_TẠO_BẰNG_caddy_hash_password }
}
EOF
sudo systemctl reload caddy
```

> SSE đã được cấu hình chuẩn (`X-Accel-Buffering: no`, no-cache) — Nginx cũng OK:
> `proxy_buffering off; proxy_read_timeout 600;`

## Cách 3: PaaS (Render / Railway / Fly.io)

Vercel/Netlify **không phù hợp** (cần process Python dài-lived cho SSE). Trên
Render/Railway: Build = `pip install -r requirements.txt && cd web && npm ci && npm run build`,
Start = `uvicorn server.main:app --host 0.0.0.0 --port $PORT`, mount disk tại `/app/data`.

## 🔐 Checklist bảo mật trước khi public

| Việc | Vì sao |
|---|---|
| Đặt sau reverse-proxy có auth (basic auth / SSO / IP allowlist) | Agent chạy lệnh shell thật trên máy bạn |
| Giữ **approval_mode = guarded** (mặc định) | Chặn `sudo`, `rm -rf /`, pipe-from-net… |
| Bật **docker_sandbox** nếu server có Docker | Lệnh chạy trong container: no-network, 512MB RAM, 1 CPU |
| Dùng `OPENROUTER_API_KEY` env, không commit key | Key leakage qua git |
| Mount riêng volume `/app/data` | Sessions/workspace tách khỏi image |

## Cấu trúc dữ liệu runtime

```
data/
├── config.json     # api_key (chmod 600), model, approval_mode
├── mcp.json        # cấu hình MCP servers
├── sessions/       # hội thoại JSON
└── workspaces/     # workspace file của từng phiên (sandbox đường dẫn)
```
