# 🔐 SECURITY — Forge Agent v0.34 private team

> Mô hình mục tiêu: **một VPS/process, nhiều tài khoản được admin mời, provider key do operator giữ**. Session/workspace có owner ACL ở application layer. Đây vẫn là môi trường cho nhóm tin cậy, **không phải sandbox OS hoặc multi-tenant isolation chống user độc hại**.

## 1. Cài provider key và tạo admin

Không dán key/password vào source, chat, Dockerfile, compose file, Web bundle hay ZIP. Chạy trong terminal tương tác:

```bash
# Nhập provider key ẩn; nếu chưa có user, lệnh này cũng tạo admin đầu tiên.
python scripts/setup_keys.py --provider openrouter --release
# Hoặc: --provider google / --provider custom

# Tạo thêm admin/member; password nhập ẩn, không có --password.
python scripts/setup_auth.py --email admin@example.com --role admin
python scripts/setup_auth.py --email member@example.com --role member

# Kiểm tra trạng thái, không in secret.
python scripts/setup_keys.py --check
python scripts/setup_auth.py --check
```

- Password tối thiểu **16 ký tự**, lưu salt + PBKDF2-HMAC-SHA256 (240.000 vòng), không lưu password thô.
- User đầu tiên phải là admin. Không có public registration; user sau do admin tạo/mời trong **⚙ → Team** hoặc CLI.
- `FORGE_DATA_DIR` nên nằm ngoài source, ví dụ `/var/lib/forge`, và phải thuộc đúng OS user chạy server.

### Runtime data

```text
$FORGE_DATA_DIR/
├── config.json               # model/policy; KHÔNG chứa provider key
├── provider-secrets.json     # OpenRouter/Google/custom key, chmod 600
├── auth.db                   # user, password/session hash, Google identity/OAuth config
├── secrets.json              # connector token nếu dùng
├── sessions/                 # mỗi session có owner_id
├── workspaces/
└── session-migration-backup/ # chỉ xuất hiện sau migration có --apply
```

Thư mục data được hạn chế quyền best-effort; `auth.db` chứa Google client secret nếu bật OIDC nên phải được bảo vệ như provider key. `data/` bị gitignore và loại khỏi release ZIP.

## 2. Browser auth và owner ACL

- Login bằng email/password hoặc Google OIDC. Không còn shared Basic/Bearer password.
- Session cookie `forge_session`: **HttpOnly + SameSite=Lax**, hết hạn sau 8 giờ; DB chỉ lưu SHA-256 của token. Bật `Secure` qua HTTPS public URL hoặc `FORGE_COOKIE_SECURE=1`.
- Cookie CSRF riêng không HttpOnly để JS same-origin đọc; mọi mutation và SSE POST cần header `X-CSRF-Token` khớp cookie. Cross-site request bị từ chối.
- Logout revoke token; disable user revoke toàn bộ session của user đó. Đổi password cũng revoke các phiên đăng nhập cũ.
- Login shell/static và `/api/health` là public; API chứa dữ liệu user yêu cầu đăng nhập. Health không trả model, endpoint hay secret.

| Quyền | Admin | Member |
|---|:---:|:---:|
| Session/workspace, fork/export/batch/battle/loop của chính mình | ✓ | ✓ |
| Chọn canonical model theo session | ✓ | ✓ |
| Audit/usage/inbox/approval/elicitation của chính mình | ✓ | ✓ |
| Đổi default model/provider/settings toàn server | ✓ | — |
| Quản lý Team, Google login, MCP/connectors toàn server | ✓ | — |
| Mở arbitrary host workspace | ✓ | — |
| Dùng MCP tools với credential toàn server | ✓ | — |
| Cài/xoá/sửa global skill | ✓ | — |
| Tạo/trust/toggle project skill trong workspace mình | ✓ | ✓ |

Owner trả về `404` khi truy cập session của user khác để không xác nhận sự tồn tại. ACL không thay thế OS sandbox: agent/shell vẫn chạy dưới cùng OS account theo policy server, vì vậy không cấp account cho người không tin cậy.

## 3. Model và provider boundary

Canonical model ID:

```text
openrouter:vendor/model       # qua OpenRouter
google:gemini-...             # Gemini direct
custom:model                  # OpenAI-compatible endpoint do admin cấu hình
```

`openrouter:google/...` là model vendor Google **qua OpenRouter**, không phải Gemini direct. Provider key chỉ nằm trên server; client không gửi endpoint hay nhận secret. Demo/cost/fallback/sub-agent/batch/battle route theo provider của từng model, không theo active provider toàn cục.

`image_generation` mới là capability contract. **Chưa có image-generation adapter**: catalog trả rỗng với `image_generation_adapter=false`, chat yêu cầu tạo ảnh trả 501. Không coi vision (hiểu ảnh) là image generation.

## 4. Google OIDC — chỉ login, không Gmail

Cấu hình trong **⚙ → Team → Google OpenID Connect**, hoặc:

```bash
python scripts/setup_auth.py --google \
  --client-id '<oauth-client-id>' \
  --public-url 'https://forge.example.com'
```

Client secret nhập ẩn. Tạo **Web application** trong Google Cloud và đăng ký chính xác:

```text
https://forge.example.com/api/auth/google/callback
```

Flow dùng Authorization Code + PKCE S256 + state + nonce, verify ID token RS256 bằng Google JWKS, issuer/audience/expiry/nonce và `email_verified`. OAuth transaction hết hạn sau 10 phút và chỉ dùng một lần. Email phải được mời trước; user Google-only không cần password.

Scope chỉ `openid email profile`. **Không xin offline access hoặc Gmail scope.** Google login không tạo quyền Gmail/Drive; connector OAuth là hệ thống riêng và chỉ admin quản lý.

## 5. HTTPS, CORS và rate limit

Production qua mạng bắt buộc HTTPS reverse proxy:

```caddy
forge.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

- Đặt `FORGE_PUBLIC_URL=https://forge.example.com` hoặc `FORGE_COOKIE_SECURE=1`.
- Không expose uvicorn trực tiếp. Nginx cần `proxy_buffering off` và timeout phù hợp cho SSE.
- Release mặc định same-origin. Chỉ thêm origin HTTPS chính xác vào `FORGE_CORS_ORIGINS` khi thật sự cần; `*` làm server từ chối khởi động ở release.
- LLM endpoints (`chat`, `compact`, `init`, `loop`, `batch`, `battle`) mặc định giới hạn **20 request/phút/user+IP**, trả `429 + Retry-After`. Login cũng có giới hạn brute-force theo IP+email.
- Rate limit là in-process cho **một VPS/process**. Nhiều worker/instance cần quota tổng ở proxy/gateway. Đây không phải billing quota; admin vẫn phải theo dõi chi phí provider.

## 6. Subprocess và connector secrets

Shell, hook, background task, git/checkpoint/worktree, review, LSP và skill manager dùng sanitized environment, loại provider/admin credential. Provider error được redact trước khi trả SSE/log.

MCP stdio chỉ nhận secret khai báo explicit trong `env` của server đó. Vì MCP/connectors đang dùng credential toàn server, **member không nạp MCP tools và không quản lý connector** trong Phase 1. Không cài MCP/hook không tin cậy: chúng là code chạy trên server.

## 7. Nâng cấp từ v0.33 — migration tường minh

Session cũ có `owner_id=""` bị ẩn, **không tự gán cho người đăng nhập đầu tiên**. Kiểm tra trước:

```bash
python scripts/migrate_sessions.py --email admin@example.com
```

Đây là dry-run. Sau khi xác nhận đúng user:

```bash
python scripts/migrate_sessions.py --email admin@example.com --apply
```

Lệnh chỉ gán session owner rỗng, không đụng session đã thuộc user khác, ghi atomic và tạo backup trong data. Không in nội dung hội thoại.

## 8. Rotation và thu hồi

1. Disable user trong Team để revoke browser sessions ngay; giữ lại dữ liệu theo retention policy của operator.
2. Đổi provider key bằng `setup_keys.py`; thu hồi key cũ tại provider.
3. Đổi Google client secret trong Team hoặc `setup_auth.py --google`; không để secret cũ trong log/backup không cần thiết.
4. User đổi password qua `POST /api/auth/password`; các browser session cũ bị revoke. Không dùng shared password.
5. Kiểm tra `--check`, HTTP smoke và quyền sau mỗi rotation/update.

## 9. Regression và giới hạn kiểm chứng

```bash
python scripts/test_v033.py
python scripts/test_v034.py
```

Suite dùng fake credential và data tạm. v0.34 kiểm AuthStore, owner ACL, CSRF/cookie, Team, model routing, background owner, OIDC flow giả và RS256/JWKS local, migration, member MCP/skill isolation.

**Kiểm thử OIDC giả không thay thế Google OAuth thật trên production.** Sau khi cấu hình client thật, admin cần smoke: start → Google consent → callback → logout → login lại, và kiểm tra uninvited/disabled account. Không ghi client secret/token vào test log.
