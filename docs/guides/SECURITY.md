# 🔐 SECURITY — Forge Agent v0.36 account & access

> Mô hình mục tiêu: **một VPS/process, account do admin tạo hoặc public signup opt-in, provider key do operator giữ**. Session/workspace có owner ACL ở application layer. Đây vẫn là môi trường cho nhóm tin cậy, **không phải sandbox OS hoặc multi-tenant isolation chống user độc hại**.

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
- User đầu tiên phải là admin. Mặc định invite-only; admin có thể bật public signup trong **⚙ → Team**. Public endpoint không thể tạo admin và vẫn bị chặn trước khi bootstrap admin.
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

AuthStore closes its SQLite connection after each operation, including transaction and setup failures. This is not a concurrency or resource limit: concurrent requests can still open many connections, contend on SQLite locks/WAL, or block on I/O. The in-process lock does not coordinate multiple workers. Monitor and test the intended deployment and keep independent backups.

### Session identifier boundary (implementation update)

Session IDs must now match exactly: nonempty alphanumeric Unicode, hyphen or underscore, at most 200 characters and 240 UTF-8 bytes. Invalid aliases are rejected rather than stripped, and stored IDs must match their filenames. This closes a tested authenticated workspace-file traversal through a malformed owned-session ID. Old identifiers relying on normalization or exceeding these bounds will not resolve. This check is not an OS sandbox and does not make arbitrary workspace pointers, direct helper calls or filesystem races safe.

## 2. Browser auth, public signup và owner ACL

### Public signup opt-in (v0.35)

- Mặc định tắt khi cài/nâng cấp. Bật trong **⚙ → Team**, hoặc dùng `FORGE_ALLOW_REGISTRATION=1` làm **default ban đầu**; lựa chọn admin ghi trong Auth DB được ưu tiên sau đó.
- `POST /api/auth/register` yêu cầu CSRF và admin đã tồn tại. Payload không nhận `role`/`enabled`; user mới luôn là member active, password ≥16 ký tự, sau đó server phát session cookie và xoay CSRF.
- Giới hạn trong một process: 5 lượt/15 phút/IP và 3 lượt/15 phút/email; trả `429 + Retry-After`. Admin tắt signup không revoke user đã tạo; disable từng user vẫn revoke ngay.
- **Chưa có SMTP email verification.** Email/password tự đăng ký chưa chứng minh quyền sở hữu email. Khi mở public Internet cần HTTPS, gateway quota và nên có CAPTCHA/approval workflow phù hợp; rate-limit in-process không phải toàn bộ chống abuse.
- Nếu signup đang mở, Google OIDC cũng có thể tạo member cho email Google mới; nếu đóng, Google trở lại invite-only. Google `email_verified` vẫn bắt buộc.

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
| Quản lý Team, public signup, Google login, MCP/connectors toàn server | ✓ | — |
| Xem và dừng loop đang chạy của mọi user (`/api/admin/loops`) | ✓ | — |
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

### Persistent keys/model và error boundary (v0.36)

- Settings chỉ nhận boolean `provider_keys` cho từng provider và mask giả; không có API đọc lại secret thô. Browser chỉ lưu preference `forge-key-provider`, không lưu key. Đổi provider xoá draft để tránh ghi nhầm secret sang provider khác.
- `PATCH /api/sessions/{sid}/model` đi qua cùng cookie auth, CSRF và `ScopedSessionStore`: member chỉ đổi session mình, session user khác trả 404. Model invalid không ghi đè giá trị đã lưu.
- HTTP error client giữ status/endpoint nhưng redact các dạng provider key/Bearer token; FastAPI 422 chỉ lấy location/message, không echo trường `input` có thể chứa secret. SSE phải có `done`, nếu không client báo stream bị cắt.

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

Flow dùng Authorization Code + PKCE S256 + state + nonce, verify ID token RS256 bằng Google JWKS, issuer/audience/expiry/nonce và `email_verified`. OAuth transaction hết hạn sau 10 phút và chỉ dùng một lần. Khi signup tắt, email phải được tạo trước; khi signup mở, Google user mới chỉ trở thành member. User Google-only không cần password.

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
- Signup giới hạn **5 lượt/15 phút/IP + 3 lượt/15 phút/email**; request public vẫn cần CSRF.
- Rate limit là in-process cho **một VPS/process**. Nhiều worker/instance cần quota tổng ở proxy/gateway. Đây không phải billing quota; admin vẫn phải theo dõi chi phí provider.

### Workspace paths and context imports

Search, repository maps, the workspace tree and workspace exports skip symbolic-link entries. Context imports from project rules and memory are restricted to the workspace root; global context imports are restricted to the data root. Existing external `@import` paths and symlinked files in exports may therefore no longer work. Memory write/clear operations reject symlinked memory files or backups.

The direct file preview endpoint reads at most 4 MiB plus one byte and returns HTTP 413 rather than truncated text for larger files. This is a compatibility change for clients that previously opened larger files; the limit does not bound total memory, serialization, concurrent requests or other file-consuming endpoints. The UI makes server-detected binary/non-UTF-8 preview read-only and blocks its editor save. The server marks any NUL-containing or invalid UTF-8 file as non-editable, but this is not comprehensive binary detection: arbitrary binary bytes that happen to be valid UTF-8 without NUL can still be treated as text. Files in other encodings are also read-only. The editor restores a file's uniform LF, CRLF or CR line-ending style when saving; mixed-line-ending files are shown read-only to avoid silently changing their bytes. Files with no existing line ending use LF for newly entered line breaks. This is not a general file-integrity or concurrency guarantee; verify important files and maintain backups. This does not prevent writes through other API clients or tools. The New File action uses a separate exclusive-create endpoint and returns 409 if the destination already exists. Upload now skips existing destination names by default, including symlinks; API clients can explicitly request overwrite with multipart form field `overwrite=true`, but the web UI does not offer that option. Only the first 20 supplied file parts are considered, including ones subsequently skipped; later parts are reported in the successful response with their original positions, and long names are truncated. Parser or request errors can prevent that report. Ordinary PUT save and explicit overwrite upload can still overwrite files. Exclusive create is not a general filesystem isolation or transactional guarantee, and an I/O failure may leave a partially created file or directories. The editor requests confirmation before discarding dirty content for normal file/session navigation, New File, fork, logout and deletion of the active session, and asks the browser to warn on unload. This is not durable storage: browser unload prompts may be suppressed, forced authentication expiry clears the editor without confirmation, crashes can lose edits, and saves already sent can complete after navigation. Other clients and external writes are not synchronized. These checks are not an OS-level isolation boundary: concurrent filesystem changes, hard links, platform-specific reparse points, shell commands and other workspace consumers need separate controls and review.

### Editor save versions: best-effort conflict detection

Editable previews return a SHA-256 hash of the exact bytes. The web editor sends that version to the dedicated `PUT /api/workspace/file/conditional` route, which requires a valid version; older servers without this route reject the editor save rather than silently ignoring the precondition. The server verifies the bounded current bytes before and after the checkpoint and rejects changed, missing, unreadable or oversized files with 409. The draft stays in the editor on conflict; copy it before reopening. The editor refuses editing/saving if a required version is missing or malformed. API clients using the legacy PUT route without `expected_version` retain legacy overwrite behavior, and tools and explicit overwrite uploads do not use this precondition. On a non-conflict failure the editor cannot tell whether the server already wrote the file; copy the draft and inspect the workspace before deciding what to do.

Versioned PUT saves also reject content larger than 4 MiB when encoded as UTF-8 before snapshot or write, and the editor checks after restoring line endings while retaining an oversized draft for copying or shortening. This is not a request-body, concurrency or total-memory limit: parsing happens first and encoding allocates memory. Legacy PUTs without a version, create, uploads and tools do not use this particular save limit. Versioned PUT also rejects NUL characters before snapshot or write, and the editor keeps such a draft for copying or correction. Legacy PUTs, create, uploads and tools can still write NUL-containing files, which preview classifies as binary. These checks do not guarantee future editability after external modification, mixed line endings or other preview/filesystem constraints.

This is **not an atomic lock or compare-and-swap**: another writer can modify the path after the final read or during the write. Changes that return to identical bytes, or identical-content replacements, are not detected. A checkpoint may be created before a post-checkpoint conflict is noticed; it may exclude the relevant file. Each check reads up to 4 MiB plus one byte synchronously, with additional memory and I/O costs under concurrency. Filesystem/path races, partial writes and non-durable drafts still apply. Maintain independent backups and coordinate writers externally when stronger protection is required.

### Editor deletion versions

Binary/non-UTF-8 previews now also expose the SHA-256 hash of their bounded bytes. The editor requires a valid version for deletion and calls `DELETE /api/workspace/file/conditional` with `expected_version`; a distinct route prevents older servers from silently ignoring a version argument. The server checks before and after checkpointing and rejects changed, missing, unreadable or oversized files rather than deleting them. A conflict leaves the editor draft available to copy. The old DELETE endpoint still accepts requests without a version, and other tools and clients can bypass this check.

The editor serializes its own save/delete operations and blocks repeated deletes while a deletion is pending. Typing can continue while waiting; if the same editor changes before a successful deletion completes, the displayed draft remains read-only for copying rather than being silently discarded. An uncertain delete response may mean the file was already deleted: copy any draft and inspect the workspace. A stuck request can keep save/delete disabled until it settles or the page reloads; the draft is not durable. This guard does not coordinate other tabs, API clients or tools.

This is best-effort, **not an atomic check-and-unlink**: concurrent changes after the final check, identical-byte replacement and same-bytes ABA can still result in deletion. A post-checkpoint conflict may still leave a checkpoint. The hash is visible to authorized preview clients and included in the delete URL, which may be logged; it can reveal equality or enable guessing of known file contents. Concurrent reads, filesystem/path races, checkpoint exclusions and non-durable draft caveats remain. Coordinate writers and retain backups when stronger protection is needed.

### Checkpoint undo can delete files

Undo is destructive and is not a substitute for an independent backup. It restores the most recent snapshot and then removes it from the undo stack; it also removes untracked files. Checkpoints made through agent tools and direct workspace file saves, deletes and uploads are taken before the operation, when available and enabled. Upload takes one snapshot before its first eligible write, not one per file. A created checkpoint does not guarantee that a particular file is included: configured exclusions and Git ignore rules can leave it out. These endpoints report a warning if no checkpoint was confirmed, but may still modify files. An upload may partially write files before an error or cancellation, and its error response may not enumerate those writes. Concurrent changes and filesystem/symlink races are not serialized; snapshots may also be created for operations that later fail or change nothing. The upload handler reads at most 20 MiB plus one byte from each eligible parsed file to check its size. The upload route also limits the incoming ASGI request body to 401 MiB including multipart framing and fields, returning 413 when exceeded. For streamed multipart overflow, parser spool cleanup has been verified on two FastAPI/Starlette version pairs; this is not a guarantee for every dependency version, disconnect, cancellation or crash. This is not a total process memory or disk bound: the framework may spool parsed uploads before the handler, ASGI/proxy buffers may already hold data, and concurrent requests multiply resource use. Other routes are not covered by this upload-specific limit. Set independent ingress limits, concurrency/timeouts and monitor temporary storage. The cleanup excludes configured checkpoint exclusion names, such as `node_modules` and `.venv`, but other untracked files can still be deleted. Before checkout, undo checks the target tree and refuses to proceed if a tracked path matches an exclusion or if the check cannot complete. This is a conservative preflight, not a filesystem isolation guarantee: concurrent changes, path aliases and platform-specific behavior can still matter. Failures or cancellation can leave the workspace partially changed. Inspect and back up important data before undo, especially for an opened external workspace.

### `fetch_url` network boundary

The agent's `fetch_url` tool validates every redirect before following it, rejects non-public DNS answers and URL credentials, and connects to a validated IP while retaining the hostname for Host/TLS verification. It ignores environment proxy and certificate configuration (`trust_env=False`); installations requiring those settings need an explicitly designed and tested egress solution. The tool retains at most 128,000 response body bytes, rejects compressed responses, and applies a cooperative 45-second overall deadline across DNS, redirects, and streaming. The deadline cannot interrupt synchronous work or guarantee immediate cleanup, and DNS resolver threads may continue after timeout. The byte limit is not a bound on all process memory. These checks do not replace network-level egress restrictions or an OS sandbox.

## 6. Subprocess và connector secrets

### Shell-tool sandbox and approval behavior

If the background output pump cannot confirm an integer process exit code, task details and scoped summaries warn that the result is unknown instead of inventing an exit code. The task remains conservatively counted as running, which does not prove it is alive and can occupy a slot; the pump does not automatically retry a failed wait. If a stop signal has already been sent but its wait failed, timed out or was cancelled, another stop request retries the bounded process wait without resending the signal. A direct-process fallback remains unconfirmed for the group even after the leader exits. This is not proof that escaped descendants stopped; inspect and supervise externally as needed.

Background output decoding waits for the reader to stop before finalizing an incomplete UTF-8 sequence; process exit alone does not prove that an inherited output pipe has closed. Invalid or truncated bytes are displayed with replacement characters, and an open pipe can leave an incomplete sequence pending. Buffer truncation and read failures can still lose output.

If a background output pump is cancelled before it starts or while reading, task details and scoped summaries warn that output may be incomplete and, unless exit was separately confirmed, that the exit status is unconfirmed. Cancellation during the process wait warns only about exit status. Cancellation does not terminate the process or restart draining: an unread pipe can fill and block the child. Inspect and stop it separately if needed; warnings are in-memory and may not be observable during abrupt shutdown.

Background task output includes a persistent warning in both task details and scoped summaries if reading the output stream raises an exception. Previously captured bytes and the process exit code are still shown; the tool request's `ok` field reflects whether the check itself succeeded, not whether all child output was collected. Exception text is not included in that warning. A read failure does not automatically terminate the child; an undrained pipe may block it, so inspect and stop it if needed.

Background stop errors do not include raw OS exception messages when group and direct signalling fail, or when direct signalling fails on the non-POSIX path. This limits exposure of exception details in those tool responses; it is not a general redaction guarantee for other errors, logs, commands, or child output. The stop remains unconfirmed and may need external investigation.

The `kill_background` tool returns `ok: false` when stop cleanup is unconfirmed, including when only the direct leader was signalled successfully. This is uncertainty, not proof the leader is still alive; `ok: true` is also not proof that escaped descendants or containers stopped. The separate `check_background` tool's `ok` indicates a successful query, not a confirmed process outcome. The internal string-returning `background.kill()` API conveys uncertainty in its message rather than a boolean.

A missing background process group is not treated as proof that a group-stop signal was delivered. If the direct process appears alive, the server attempts a direct-process stop and warns that group termination remains unconfirmed; if the leader has exited or the direct stop fails, it reports an error rather than claiming the group was killed. This warning is retained in task details and scoped summaries while the task entry exists. A successful group signal still does not prove that escaped descendants or containers were stopped.

On Windows a shell command runs as a child of `cmd.exe`, so ending the direct process alone would leave the command running. The commands of the `run_command` and `run_background` tools, of lifecycle hooks and of the legacy `on_file_change` hook are therefore placed in a Job Object before they run, and a foreground timeout or cancellation, `kill_background` and a hook timeout or cancellation terminate the whole job. If a command cannot be placed in a job, it is ended before it runs and its start is reported as an error; for a hook this is a failed start like any other, so a `pre_tool_use` hook that did not run does not block the tool call. For a running task `kill_background` terminates the job, waits for the direct process and then, for up to five seconds, for the job to report no live process; when it does, the answer is `ok: true`. If the job does not report that in time, the answer is `ok: false` and says that the command tree is still running; unlike on POSIX, a repeated stop request then terminates the job again. This is neither a sandbox nor a guarantee for every process. A process outside the job, such as a container or a process that the command had another service start, is not stopped. A command that ends on its own leaves what it detached running, and a command that is running when the server process is ended abruptly is not stopped by the job. MCP servers, language servers, Git commands, review, auto-commit and the skill manager are started without a job; where the server stops one of them, it ends only the direct process. After a hook timeout the result still says that process cleanup is unconfirmed, whether or not the job was emptied. The stop after a foreground timeout, after `kill_background` and after a hook timeout was measured on one Windows 11 machine with CPython 3.14.7; the rest of this paragraph is read from the code. See `docs/reports/IMPLEMENTATION_PROGRESS.md`.

During graceful shutdown, the server waits up to an additional two seconds for currently tracked background stdout pumps after attempting task termination, and logs a warning if any remain pending. A timed-out pump is not cancelled by that wait, but the event loop may subsequently stop while it is still pending. This is not an absolute shutdown deadline or a process-tree guarantee: earlier spawn/kill waits also take time, descendants can escape process groups and hold pipes open, late spawns can appear after the pump snapshot, and abrupt termination bypasses graceful cleanup. Monitor shutdown warnings and use external process/container supervision.

When `docker_sandbox` is enabled, the foreground `run_command` and background `run_background` agent tools use Docker. If the Docker executable is unavailable, these tools are blocked rather than silently running on the host. A Docker launch failure also does not fall back to host execution. In `ask` mode, warning and dangerous commands from either tool require approval; an explicitly typed workspace-terminal command remains a direct user action subject to its existing guard checks.

This sandbox applies **only to these shell-tool paths**. Hooks, LSP, MCP, Git/checkpoints and other subprocesses are not automatically sandboxed by this setting. The workspace is mounted writable, and command classification is not a security boundary. Operators must separately verify Docker daemon, mount and network behavior on their platform; process-tree and container cleanup still require further work.

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
python scripts/test_v035.py
python scripts/test_v036.py
```

Suite dùng fake credential và data tạm. v0.36 kiểm lưu/reload ba provider key, model session trước prompt, owner ACL/CSRF, provider 501 mock + redaction, SSE error/done và concurrent routing; v0.35 kiểm public signup/toggle/role guard/rate-limit/Google policy/owner isolation; v0.34 kiểm AuthStore, owner ACL, CSRF/cookie, Team, model routing, background owner, OIDC flow giả và RS256/JWKS local, migration, member MCP/skill isolation.

**Kiểm thử OIDC giả không thay thế Google OAuth thật trên production.** Sau khi cấu hình client thật, admin cần smoke: start → Google consent → callback → logout → login lại, và kiểm tra uninvited/disabled account. Không ghi client secret/token vào test log.

### Partial workspace-hook approval coverage

Normal non-demo, non-synthetic server chat, the manual compact endpoint, non-demo scheduled loop ticks (a loop started with `/loop` in chat or with `POST /api/sessions/{sid}/loop`) and non-demo `/api/batch` and `/api/battle` items check process-local admin approval for workspace hook configuration, including eligible active shared subagents. **This is not comprehensive enforcement**: demo mode (also a demo loop tick and a demo batch or battle item), synthetic operations, direct callers and other paths may bypass it. The API still reports `enforcement_active: false` with the scope name `normal_non_demo_chat_and_manual_compact`, and the web UI still names chat and manual compaction only; both understate the checked paths. Approval records expire and are lost on restart and are not shared across workers. Review the current scope in `docs/reports/WORKSPACE_HOOK_TRUST_DESIGN.md`; do not rely on approval as a sandbox or as protection from hostile workspace code. Previously executed writes and hooks are not rolled back when a later check denies.

An approval ends 30 minutes after its review request was submitted. An administrator's decision does not extend it, and submitting the same configuration again returns the same request. A scheduled loop in a workspace that has a hook configuration therefore runs only while that approval lasts: its first tick runs at once, and the first tick after the approval has ended is denied. A denied tick stops the loop; the loop status and `/loop` in chat report `hook_trust_denied`. With the default interval of 30 minutes the denied tick is the second one. To continue, submit a new review request, have it approved and start the loop again. A loop in a workspace without a hook configuration needs no approval.

Every loop tick, demo or not, first checks that the owner account still exists and is enabled, and then opens the session through that owner's own store, with or without a hook configuration. A tick whose account or session is gone ends the loop; the loop status names the reason (`owner_disabled`, `owner_missing`, `owner_check_failed` or `session_deleted`). Disabling an account also ends that account's loops at once, including a tick that is running, and they do not resume when the account is enabled again. Deleting a session stops its loop in the same way. An administrator can list the running loops of all accounts with `GET /api/admin/loops`, which leaves out the task text, and stop one with `DELETE /api/admin/loops/{sid}`. A stopped or denied tick does not undo what it or earlier ticks did. A chat turn is not stopped by a deletion: a session that is deleted while a chat turn is running on it is saved again by that turn (issue #16).
