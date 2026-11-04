"""Command-safety guard: classify shell commands before the agent runs them.

Modes (stored in config as "approval_mode"):
  "guarded" (default) — SAFE and WARN run; DANGEROUS is refused and reported back
                        to the model/user.
  "auto" (yolo)       — everything runs (only for trusted/private use).

If Docker is available AND env FORGE_DOCKER_SANDBOX=1, commands run inside a
locked-down container instead (no network, read-only fs except /work).
"""
import re
import shutil

# (compiled regex, level, human reason)
_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # ---- DANGEROUS ----
    (re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*[rf][a-zA-Z]*\s+(/|~|\$HOME|\*)", re.I), "danger",
     "xóa đệ quy từ gốc/home"),
    (re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?[a-zA-Z]*\s+\.", re.I), "danger", "xóa đệ quy thư mục hiện tại"),
    (re.compile(r"\b(mkfs|fdisk|parted|dd\s+if=.*of=/dev/)", re.I), "danger", "ghi/thao tác ổ đĩa thô"),
    (re.compile(r"\b(shutdown|reboot|halt|poweroff)\b", re.I), "danger", "tắt/khởi động lại máy"),
    (re.compile(r"\bsudo\s", re.I), "danger", "dùng sudo"),
    (re.compile(r"\b(chmod|chown)\s+(-\w+\s+)?(777|[0-7]{3}\s+/(etc|usr|bin|sbin|boot))", re.I), "danger",
     "đổi quyền hệ thống"),
    (re.compile(r"(curl|wget)[^|;]*\|\s*(sudo\s+)?(ba)?sh", re.I), "danger", "pipe script từ mạng thẳng vào shell"),
    (re.compile(r":\(\)\s*\{.*\};\s*:", re.S), "danger", "fork bomb"),
    (re.compile(r"\bhistory\s+-c\b|\bshred\b|\bwipefs\b", re.I), "danger", "xóa vết/đĩa"),
    (re.compile(r">\s*/dev/(sd|nvme|hd)", re.I), "danger", "ghi thẳng vào device"),
    # ---- WARN (network / install / process / big delete) ----
    (re.compile(r"\b(curl|wget|ftp|scp|rsync)\b", re.I), "warn", "truy cập mạng"),
    (re.compile(r"\b(pip3?\s+install|npm\s+(install|i|add)|yarn\s+add|apt(-get)?\s+install|brew\s+install)\b", re.I),
     "warn", "cài đặt phần mềm"),
    (re.compile(r"\bgit\s+(push|reset\s+--hard|clean\s+-[a-zA-Z]*f|rebase)\b", re.I), "warn", "git thay đổi mạnh"),
    (re.compile(r"\brm\s+-", re.I), "warn", "xóa file"),
    (re.compile(r"\b(kill|pkill|killall)\b", re.I), "warn", "dừng tiến trình"),
    (re.compile(r"\bdocker\s", re.I), "warn", "điều khiển Docker"),
    (re.compile(r"\benv\s*\|\s*|\bprintenv\b|\bcat\s+/etc/(passwd|shadow)\b", re.I), "warn", "đọc biến môi trường/hệ thống"),
    (re.compile(r"\bssh\s|scp\s", re.I), "warn", "kết nối máy khác"),
]

DOCKER_AVAILABLE = shutil.which("docker") is not None

_NET_RX = re.compile(
    r"\b(curl|wget|ftp|scp|rsync|ssh|telnet|nc|netcat|ping)\b"
    r"|\b(pip3?|npm|yarn|pnpm|bun|cargo|go|gem|composer|dotnet)\s+(install|add|publish|upload)\b"
    r"|\bgit\s+(push|pull|fetch|clone|remote)\b"
    r"|\b(apt|apt-get|brew|choco|winget)\s+(install|upgrade)\b"
    r"|\brsync\b|\bhuggingface-cli\b|\bollama\s+(pull|push)\b", re.I)


def _config_patterns() -> tuple[list[str], list[str]]:
    """Đọc allow/deny glob từ config.json (vd "git push *", "rm -rf *")."""
    from . import config
    cfg = config.load_config()
    deny = [str(x).lower() for x in (cfg.get("deny_commands") or []) if str(x).strip()]
    allow = [str(x).lower() for x in (cfg.get("allow_commands") or []) if str(x).strip()]
    return deny, allow


def assess_command(cmd: str) -> dict:
    """Return {"level": "safe"|"warn"|"danger", "reasons": [..]}.

    Config patterns (config.json): deny_commands chặn tuyệt đối (ưu tiên cao nhất,
    kể cả khi allow match); allow_commands nâng warn → safe (danger vẫn danger).
    """
    from fnmatch import fnmatch
    from . import config as _cfg
    c = (cmd or "").strip().lower()
    deny, allow = _config_patterns()
    # Network kill-switch (sandbox một phần cho máy không có Docker — cả Windows):
    # block_network=true → mọi lệnh ra mạng bị xếp danger bất kể mức khác.
    if _cfg.load_config().get("block_network") and _NET_RX.search(c):
        return {"level": "danger",
                "reasons": ["block_network=true — lệnh ra mạng bị chặn (tắt trong config nếu cần)"]}
    reasons: dict[str, list[str]] = {"danger": [], "warn": []}
    for rx, level, reason in _PATTERNS:
        if rx.search(cmd or ""):
            if reason not in reasons[level]:
                reasons[level].append(reason)
    if reasons["danger"]:
        return {"level": "danger", "reasons": reasons["danger"]}
    if reasons["warn"]:
        if any(fnmatch(c, d) or fnmatch(d, c) for d in deny):
            return {"level": "danger", "reasons": reasons["warn"] + ["khớp deny_commands trong config"]}
        if any(fnmatch(c, a) or fnmatch(a, c) for a in allow):
            return {"level": "safe", "reasons": []}
        return {"level": "warn", "reasons": reasons["warn"]}
    # safe theo regex — nhưng deny vẫn phải chặn (ai định nghĩa deny là muốn chặn)
    if any(fnmatch(c, d) or fnmatch(d, c) for d in deny):
        return {"level": "danger", "reasons": ["khớp deny_commands trong config"]}
    return {"level": "safe", "reasons": []}



def guard_message(cmd: str, verdict: dict) -> str:
    return (
        "BLOCKED by safety guard: lệnh này bị xếp loại NGUY HIỂM "
        f"({'; '.join(verdict['reasons'])}). "
        "Không tự ý tìm cách vòng qua guard. Hãy giải thích cho người dùng tại sao cần lệnh này "
        "và đề nghị họ chạy lại ở chế độ 'auto' (YOLO) trong Settings nếu họ chấp nhận rủi ro. "
        f"Lệnh bị chặn: {cmd[:300]}"
    )


def docker_wrap(cmd: str, image: str = "python:3.12-slim") -> str:
    """Wrap a command to run inside a sandboxed container (used when available)."""
    quoted = cmd.replace("'", "'\\''")
    return (
        f"docker run --rm -i --network=none --pids-limit=256 "
        f"--memory=512m --cpus=1 --cap-drop=ALL --security-opt=no-new-privileges "
        f"-v \"$PWD\":/work -w /work {image} bash -c '{quoted}'"
    )
