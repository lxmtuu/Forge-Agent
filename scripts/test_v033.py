"""Suite v0.33 "Shared-server security" — toàn bộ dùng fake key + data tạm.

Secret store/password hash · Google/OpenRouter/custom provider · sanitized env cho
shell/hook/background/git/MCP · release auth/settings lock/CORS/rate limit ·
terminal setup không echo · API/Web không chứa secret.

Chạy: python scripts/test_v033.py
"""
import ast
import asyncio
import base64
import contextlib
import importlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="forge-v033-"))
os.environ["FORGE_DATA_DIR"] = str(TMP / "data")

# Không đọc/dùng credential thật của máy chạy test. Các biến này chỉ được gán fake sau.
ENV_CLEAR = [
    "OPENROUTER_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY", "FORGE_CUSTOM_API_KEY", "FORGE_ADMIN_TOKEN",
    "FORGE_SETUP_TOKEN", "FORGE_PROVIDER", "FORGE_MODEL", "FORGE_RELEASE_MODE",
    "FORGE_CORS_ORIGINS", "FORGE_RATE_LIMIT_PER_MIN", "FORGE_PROFILE",
]
for _name in ENV_CLEAR:
    os.environ.pop(_name, None)

from engine import config
from engine import secrets as secretstore

FAKE_OR = "sk-or-v1-FAKE-V033-0123456789-ONLY-FOR-TESTS"
FAKE_GOOGLE = "AIza-FAKE-V033-0123456789-ONLY-FOR-TESTS"
FAKE_CUSTOM = "custom-FAKE-V033-0123456789-ONLY-FOR-TESTS"
PASSWORD = "forge-v033-fake-password-not-a-real-secret"
PASS, FAIL = [], []


def check(name):
    def deco(fn):
        async def run():
            try:
                await fn()
                PASS.append(name)
                print(f"  ✓ {name}", flush=True)
            except Exception as e:  # noqa: BLE001 — test harness phải gom mọi lỗi để báo đủ suite
                FAIL.append((name, str(e)))
                print(f"  ✗ {name}: {e}", flush=True)
                traceback.print_exc(limit=4)
        return run
    return deco


def reset() -> None:
    """Xoá chỉ thư mục data tạm của suite; tuyệt đối không trỏ vào data thật."""
    assert Path(os.environ["FORGE_DATA_DIR"]) == TMP / "data"
    for path in (config.CONFIG_FILE, secretstore.PROVIDER_FILE, secretstore.AUTH_FILE):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    for name in ENV_CLEAR:
        os.environ.pop(name, None)
    if "server.main" in sys.modules:
        sm = sys.modules["server.main"]
        sm._LLM_RATE.clear()
        sm._AUTH_RATE.clear()


def fake_env() -> None:
    os.environ.update({
        "OPENROUTER_API_KEY": FAKE_OR,
        "GOOGLE_API_KEY": FAKE_GOOGLE,
        "GEMINI_API_KEY": FAKE_GOOGLE,
        "OPENAI_API_KEY": "openai-FAKE-V033-not-real",
        "ANTHROPIC_API_KEY": "anthropic-FAKE-V033-not-real",
        "FORGE_CUSTOM_API_KEY": FAKE_CUSTOM,
        "FORGE_ADMIN_TOKEN": "admin-FAKE-V033-not-real",
    })


def basic(password: str = PASSWORD, username: str = "forge") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def reload_server():
    import server.main as sm
    return importlib.reload(sm)


async def run_process(*args, **kwargs):
    return await asyncio.to_thread(subprocess.run, *args, check=False, **kwargs)


@check("T1 secret store: tách/migrate key khỏi config · chmod 600 · password chỉ PBKDF2 hash")
async def t1():
    reset()
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    legacy = "sk-or-v1-LEGACY-FAKE-V033-not-real"
    config.CONFIG_FILE.write_text(json.dumps({
        "provider": "openrouter", "model": "legacy-model", "api_key": legacy,
    }), encoding="utf-8")
    cfg = config.save_config({
        "api_key": FAKE_OR, "google_api_key": FAKE_GOOGLE,
        "custom_api_key": FAKE_CUSTOM, "model": "safe-model",
    })
    raw_cfg = config.CONFIG_FILE.read_text(encoding="utf-8")
    raw_secrets = secretstore.PROVIDER_FILE.read_text(encoding="utf-8")
    for secret in (FAKE_OR, FAKE_GOOGLE, FAKE_CUSTOM, legacy):
        assert secret not in raw_cfg, "key còn nằm trong config.json"
    assert json.loads(raw_secrets)["openrouter"] == FAKE_OR
    # Legacy key được migrate trước khi key mới ghi; giá trị mới phải thắng và config sạch.
    assert "api_key" not in cfg and "google_api_key" not in cfg
    assert config.get_api_key() == FAKE_OR
    assert config.get_google_api_key() == FAKE_GOOGLE
    assert config.get_custom_api_key() == FAKE_CUSTOM
    if os.name != "nt":
        assert stat.S_IMODE(secretstore.PROVIDER_FILE.stat().st_mode) == 0o600
        assert stat.S_IMODE(config.CONFIG_FILE.stat().st_mode) == 0o600

    secretstore.write_release_password(PASSWORD)
    raw_auth = secretstore.AUTH_FILE.read_text(encoding="utf-8")
    auth = json.loads(raw_auth)
    assert PASSWORD not in raw_auth and "password" not in auth
    assert auth["scheme"] == "pbkdf2_sha256" and auth["iterations"] >= 100_000
    assert secretstore.verify_release_password("forge", PASSWORD)
    assert not secretstore.verify_release_password("forge", PASSWORD + "x")
    assert not secretstore.verify_release_password("other", PASSWORD)
    if os.name != "nt":
        assert stat.S_IMODE(secretstore.AUTH_FILE.stat().st_mode) == 0o600


@check("T2 provider: Google/custom không phụ thuộc OpenRouter · endpoint/model/fallback đúng · stale custom base không đè OpenRouter")
async def t2():
    from engine import llm
    reset()
    secretstore.write_provider_key("google", FAKE_GOOGLE)
    config.save_config({"provider": "google"})
    assert config.has_llm_credentials(), "Google key riêng vẫn bị coi là demo"
    assert config.get_active_api_key() == FAKE_GOOGLE
    assert config.provider_secret_field() == "google_api_key"
    assert config.get_model() == "gemini-3.8-flash"
    url, headers = llm._endpoint(None)
    assert url == llm.GOOGLE_OPENAI_URL
    assert headers["Authorization"] == f"Bearer {FAKE_GOOGLE}"
    assert llm.resolve_sub_model("cheap", "gemini-3.8-flash") == "gemini-3.8-flash"
    assert llm.pick_fallback("gemini-3.8-flash", Exception("HTTP 503")) is None
    config.save_config({"web_search": True})
    assert not llm.resolve_model("gemini-3.8-flash").endswith(":online")

    reset()
    config.save_config({
        "provider": "custom", "custom_base_url": "http://localhost:11434/v1",
        "custom_api_key": FAKE_CUSTOM, "model": "llama-test",
    })
    assert config.has_llm_credentials()
    url, headers = llm._endpoint(None)
    assert url == "http://localhost:11434/v1/chat/completions"
    assert headers["Authorization"] == f"Bearer {FAKE_CUSTOM}"
    assert llm.resolve_sub_model("cheap", "llama-test") == "llama-test"

    reset()
    config.save_config({
        "provider": "openrouter", "api_key": FAKE_OR,
        "custom_base_url": "http://stale-invalid.example/v1",
    })
    url, headers = llm._endpoint(None)
    assert url == llm.OPENROUTER_URL, "base URL legacy đè explicit OpenRouter"
    assert headers["Authorization"] == f"Bearer {FAKE_OR}"
    # Chỉ có Google key nhưng provider OpenRouter vẫn phải demo/fail-closed.
    reset()
    secretstore.write_provider_key("google", FAKE_GOOGLE)
    config.save_config({"provider": "openrouter"})
    assert not config.has_llm_credentials()


@check("T3 sanitized_env + AST: mọi subprocess engine có env sạch, không có nhánh env=os.environ che mắt scanner")
async def t3():
    reset()
    fake_env()
    os.environ["VISIBLE_TEST_VALUE"] = "still-here"
    env = secretstore.sanitized_env()
    assert env["VISIBLE_TEST_VALUE"] == "still-here"
    for name in secretstore.SENSITIVE_ENV:
        os.environ.setdefault(name, "fake-sensitive")
        assert name not in secretstore.sanitized_env()
    explicit = secretstore.sanitized_env({"OPENROUTER_API_KEY": FAKE_OR})
    assert explicit["OPENROUTER_API_KEY"] == FAKE_OR, "explicit MCP opt-in bị chặn nhầm"

    checked = 0
    for path in (ROOT / "engine").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = ast.unparse(node.func)
            is_child = func in {
                "asyncio.create_subprocess_exec", "asyncio.create_subprocess_shell",
                "subprocess.run", "subprocess.Popen",
            }
            if not is_child:
                continue
            checked += 1
            kw = next((k.value for k in node.keywords if k.arg == "env"), None)
            assert kw is not None, f"{path}:{node.lineno} thiếu env"
            rendered = ast.unparse(kw)
            assert "environ" not in rendered, f"{path}:{node.lineno} env trực tiếp từ os.environ: {rendered}"
    assert checked >= 15, f"scan chỉ thấy {checked} subprocess — scanner có thể sai"


@check("T4 THẬT shell + hook + background: fake provider/admin key không xuất hiện trong child environment")
async def t4():
    from engine import background as bg
    from engine import hooks, tools
    reset()
    fake_env()
    ws = TMP / "child-ws"
    ws.mkdir(exist_ok=True)
    probe = ws / "probe.py"
    names = ["OPENROUTER_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "FORGE_ADMIN_TOKEN"]
    probe.write_text(
        "import json,os\nnames=" + repr(names) + "\n"
        "print(json.dumps({n:os.environ.get(n,'<missing>') for n in names}))\n",
        encoding="utf-8")
    command = f'"{sys.executable}" "{probe}"'
    out = await tools._run_command(ws, {"command": command, "timeout_sec": 20})
    assert "exit=0" in out and out.count("<missing>") == len(names), out
    assert FAKE_OR not in out and FAKE_GOOGLE not in out
    hooked = await hooks._run_cmd(command, {"test": True}, ws)
    assert hooked["code"] == 0 and hooked["out"].count("<missing>") == len(names), hooked

    tid, msg = await bg.start(command, ws)
    assert tid, msg
    for _ in range(100):
        task = bg.get(tid)
        if task and task["status"] != "running":
            break
        await asyncio.sleep(0.05)
    task = bg.get(tid)
    assert task and task["status"] == "done", task
    rendered = bg.render(task, incremental=False)
    assert rendered.count("<missing>") == len(names), rendered
    assert FAKE_OR not in rendered and FAKE_GOOGLE not in rendered


@check("T5 checkpoint snapshot/undo/list: GIT_DIR được thêm nhưng provider key không lọt vào git subprocess")
async def t5():
    from engine import checkpoints as cp
    reset()
    fake_env()
    config.save_config({"checkpoints_enabled": True})
    ws = TMP / "checkpoint-ws"
    ws.mkdir(exist_ok=True)
    calls = []
    original_available = cp.available
    original_run = cp._run_with_env
    cp.available = lambda: True

    async def fake_snapshot_run(args, env):
        calls.append((args, dict(env)))
        if "write-tree" in args:
            return 0, "tree-fake"
        if "commit-tree" in args:
            return 0, "c" * 40
        if "rev-parse" in args and "refs/heads/forge" in args:
            return 1, ""
        return 0, "true"

    try:
        cp._run_with_env = fake_snapshot_run
        result = await cp.snapshot("sid-v033", ws, "test")
        assert result == "c" * 10, result

        async def fake_undo_run(args, env):
            calls.append((args, dict(env)))
            if "rev-parse" in args and args[-1] == "refs/heads/forge":
                return 0, "a" * 40
            if "rev-parse" in args and args[-1] == "a" * 40 + "^":
                return 0, "b" * 40
            if "log" in args:
                return 0, "fake-log"
            return 0, ""

        cp._run_with_env = fake_undo_run
        undone = await cp.undo("sid-v033", ws)
        assert undone["ok"], undone
        assert await cp.list_checkpoints("sid-v033", ws) == ["fake-log"]
    finally:
        cp.available = original_available
        cp._run_with_env = original_run
    assert len(calls) >= 8
    for _args, env in calls:
        for name in secretstore.SENSITIVE_ENV:
            assert name not in env, f"checkpoint leak {name}"
        assert env.get("GIT_DIR") and env.get("GIT_WORK_TREE")


@check("T6 MCP stdio: default KHÔNG nhận provider key · chỉ env khai báo explicit mới được opt-in")
async def t6():
    from engine import mcp
    reset()
    fake_env()
    captured = []
    original = asyncio.create_subprocess_exec

    class FakeProc:
        def kill(self):
            return None

    async def fake_create(*args, **kwargs):
        captured.append(dict(kwargs["env"]))
        return FakeProc()

    async def fake_request(method, params, timeout):
        if method == "initialize":
            return {"serverInfo": {"name": "fake-mcp"}}
        return {"tools": []}

    async def fake_send(obj):
        return None

    async def start_one(extra):
        srv = mcp.McpServer("fake", "fake-command", [], extra)
        srv._request = fake_request
        srv._send = fake_send
        await srv.start()
        assert srv.status == "ready", srv.error
        await srv.stop_quiet()

    asyncio.create_subprocess_exec = fake_create
    try:
        await start_one(None)
        await start_one({"OPENROUTER_API_KEY": FAKE_OR})
    finally:
        asyncio.create_subprocess_exec = original
    assert len(captured) == 2
    assert "OPENROUTER_API_KEY" not in captured[0]
    assert "GOOGLE_API_KEY" not in captured[0] and "FORGE_ADMIN_TOKEN" not in captured[0]
    assert captured[1]["OPENROUTER_API_KEY"] == FAKE_OR
    assert "GOOGLE_API_KEY" not in captured[1], "opt-in một key không được mở toàn bộ secret"


@check("T7 Web/API dev: save key vào secret store · health/settings/mcp không trả full secret · browser storage không lưu credential")
async def t7():
    from fastapi.testclient import TestClient
    reset()
    sm = reload_server()
    with TestClient(sm.app) as client:
        response = client.post("/api/settings", json={"api_key": FAKE_OR})
        assert response.status_code == 200, response.text
        assert FAKE_OR not in response.text
        health = client.get("/api/health")
        settings = client.get("/api/settings")
        assert health.status_code == settings.status_code == 200
        assert FAKE_OR not in health.text + settings.text
        assert health.json()["key_masked"] == config.mask_key(FAKE_OR)
        # MCP config có explicit env nhưng status API không serialize env/secret.
        from engine.mcp import save_servers
        save_servers([{"name": "fake", "command": "x", "args": [], "enabled": False,
                       "env": {"OPENROUTER_API_KEY": FAKE_OR}}])
        mcp_response = client.get("/api/mcp")
        assert mcp_response.status_code == 200 and FAKE_OR not in mcp_response.text
    assert secretstore.read_provider_key("openrouter") == FAKE_OR
    assert FAKE_OR not in config.CONFIG_FILE.read_text(encoding="utf-8")
    for path in (ROOT / "web" / "src").rglob("*"):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if "localStorage" in line:
                lowered = line.lower()
                assert not any(word in lowered for word in ("api_key", "password", "authorization", "key_masked")), \
                    f"credential browser storage: {path}: {line}"


@check("T8 release fail-closed: thiếu auth 503 · thiếu/sai login 401 · Basic/Bearer đúng 200 · Settings/keycheck 403 · static cũng bị khóa")
async def t8():
    from fastapi.testclient import TestClient
    reset()
    config.save_config({"provider": "openrouter", "api_key": FAKE_OR, "release_mode": True})
    os.environ["FORGE_RELEASE_MODE"] = "1"
    sm = reload_server()
    with TestClient(sm.app) as client:
        missing = client.get("/api/health")
        assert missing.status_code == 503, missing.text
        assert missing.headers["X-Content-Type-Options"] == "nosniff"
        secretstore.write_release_password(PASSWORD)
        anonymous = client.get("/api/health")
        assert anonymous.status_code == 401 and "WWW-Authenticate" in anonymous.headers
        wrong = client.get("/api/health", headers=basic("wrong-fake-password-000"))
        assert wrong.status_code == 401
        ok = client.get("/api/health", headers=basic())
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert body["release_mode"] and body["settings_locked"] and not body["web_key_input"]
        assert FAKE_OR not in ok.text and PASSWORD not in ok.text
        bearer = client.get("/api/health", headers={"Authorization": f"Bearer {PASSWORD}"})
        assert bearer.status_code == 200
        locked = client.post("/api/settings", json={"model": "blocked"}, headers=basic())
        assert locked.status_code == 403
        keycheck = client.post("/api/keycheck", json={"api_key": FAKE_OR}, headers=basic())
        assert keycheck.status_code == 403 and FAKE_OR not in keycheck.text
        static_locked = client.get("/")
        assert static_locked.status_code == 401
        static_ok = client.get("/", headers=basic())
        assert static_ok.status_code == 200
        evil = client.get("/api/health", headers={**basic(), "Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in evil.headers
        assert evil.headers["Cache-Control"] == "no-store"


@check("T9 CORS: wildcard bị từ chối ở release · explicit origin cho preflight không auth · origin lạ không được ACAO")
async def t9():
    from fastapi.testclient import TestClient
    reset()
    wild_data = TMP / "wild-data"
    env = {**os.environ, "FORGE_DATA_DIR": str(wild_data), "FORGE_RELEASE_MODE": "1",
           "FORGE_CORS_ORIGINS": "*", "FORGE_ADMIN_TOKEN": "fake-admin-v033"}
    proc = await run_process(
        [sys.executable, "-c", "import server.main"], cwd=ROOT, env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    assert proc.returncode != 0, "release chấp nhận CORS wildcard"
    assert "không được chứa" in proc.stderr

    config.save_config({"provider": "openrouter", "api_key": FAKE_OR, "release_mode": True})
    secretstore.write_release_password(PASSWORD)
    os.environ["FORGE_RELEASE_MODE"] = "1"
    os.environ["FORGE_CORS_ORIGINS"] = "https://app.example"
    sm = reload_server()
    with TestClient(sm.app) as client:
        preflight = client.options("/api/health", headers={
            "Origin": "https://app.example", "Access-Control-Request-Method": "GET",
        })
        assert preflight.status_code == 200, preflight.text
        assert preflight.headers["access-control-allow-origin"] == "https://app.example"
        assert preflight.headers["access-control-allow-origin"] != "*"
        evil = client.options("/api/health", headers={
            "Origin": "https://evil.example", "Access-Control-Request-Method": "GET",
        })
        assert evil.status_code == 400
        assert "access-control-allow-origin" not in evil.headers
        ok = client.get("/api/health", headers={**basic(), "Origin": "https://app.example"})
        assert ok.status_code == 200
        assert ok.headers["access-control-allow-origin"] == "https://app.example"


@check("T10 rate limit: chat/loop request thứ 3 → 429 + Retry-After · GET vẫn hoạt động · brute-force auth bị chặn")
async def t10():
    from fastapi.testclient import TestClient
    reset()
    config.save_config({"provider": "openrouter", "api_key": FAKE_OR,
                        "release_mode": True, "rate_limit_per_min": 2})
    secretstore.write_release_password(PASSWORD)
    os.environ["FORGE_RELEASE_MODE"] = "1"
    sm = reload_server()
    with TestClient(sm.app) as client:
        for expected in (404, 404, 429):
            response = client.post("/api/sessions/no-such/chat", json={"text": "x"}, headers=basic())
            assert response.status_code == expected, (expected, response.status_code, response.text)
        assert int(response.headers["Retry-After"]) >= 1
        assert client.get("/api/health", headers=basic()).status_code == 200
        sm._LLM_RATE.clear()
        for expected in (404, 404, 429):
            response = client.post("/api/sessions/no-such/loop",
                                   json={"text": "x", "every": "1h"}, headers=basic())
            assert response.status_code == expected
        sm._AUTH_RATE.clear()
        for _ in range(10):
            assert client.get("/api/health", headers=basic("bad-fake-password-000")).status_code == 401
        blocked = client.get("/api/health", headers=basic("bad-fake-password-000"))
        assert blocked.status_code == 429 and "Retry-After" in blocked.headers
        assert client.get("/api/health", headers=basic()).status_code == 429


@check("T11 terminal setup Google+release: nhập ẩn giả lập · stdout/check không echo key/password · config sạch")
async def t11():
    from scripts import setup_keys
    reset()
    answers = iter(["gemini-3.8-flash"])
    secrets = iter([FAKE_GOOGLE, PASSWORD, PASSWORD])
    original_ask, original_secret = setup_keys._ask, setup_keys._secret
    setup_keys._ask = lambda prompt, default="": next(answers)
    setup_keys._secret = lambda prompt, allow_empty=False: next(secrets)
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            setup_keys.run_setup("google", True)
    finally:
        setup_keys._ask, setup_keys._secret = original_ask, original_secret
    printed = output.getvalue()
    assert FAKE_GOOGLE not in printed and PASSWORD not in printed
    assert config.get_provider() == "google" and config.has_llm_credentials()
    assert config.is_release_mode() and secretstore.has_release_auth()
    assert FAKE_GOOGLE not in config.CONFIG_FILE.read_text(encoding="utf-8")
    assert PASSWORD not in secretstore.AUTH_FILE.read_text(encoding="utf-8")
    proc = await run_process(
        [sys.executable, str(ROOT / "scripts" / "setup_keys.py"), "--check"],
        cwd=ROOT, env={**os.environ}, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert "google" in proc.stdout and "BẬT" in proc.stdout
    assert FAKE_GOOGLE not in proc.stdout + proc.stderr
    assert PASSWORD not in proc.stdout + proc.stderr


@check("T12 redaction + Web build: provider echo key bị xoá · bundle có release lock/setup hint · data/ bị gitignore")
async def t12():
    from engine import llm
    reset()
    leaked = f"provider echoed {FAKE_OR} và Bearer {FAKE_OR}"
    cleaned = llm._redact_error(leaked, {"Authorization": f"Bearer {FAKE_OR}"})
    assert FAKE_OR not in cleaned and "<redacted>" in cleaned
    bundles = list((ROOT / "server" / "static" / "assets").glob("*.js"))
    assert bundles, "thiếu Web build"
    js = "\n".join(p.read_text(encoding="utf-8") for p in bundles)
    assert "settings_locked" in js and "scripts/setup_keys.py" in js
    assert FAKE_OR not in js and FAKE_GOOGLE not in js and PASSWORD not in js
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/" in ignored
    source = (ROOT / "web" / "src" / "components" / "SettingsModal.tsx").read_text(encoding="utf-8")
    assert "disabled={saving || !dirty || locked}" in source
    assert "provider-secrets.json" in source
    launch_source = (ROOT / "scripts" / "launch.py").read_text(encoding="utf-8")
    assert 'FORGE_HOST", "127.0.0.1"' in launch_source
    assert '"--host", HOST' in launch_source
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "127.0.0.1:8000:8000" in compose
    assert "OPENROUTER_API_KEY=" not in compose and "GOOGLE_API_KEY=" not in compose
    cli_source = (ROOT / "cli" / "main.py").read_text(encoding="utf-8")
    tui_source = (ROOT / "tui" / "app.py").read_text(encoding="utf-8")
    assert "provider_secret_field" in cli_source and "provider_secret_field" in tui_source


async def main():
    print(f"=== SUITE v0.33 Shared-server security — data tạm: {TMP} ===")
    for fn in [t1, t2, t3, t4, t5, t6, t7, t8, t9, t10, t11, t12]:
        await fn()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for name, err in FAIL:
            print(f"  FAIL {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
