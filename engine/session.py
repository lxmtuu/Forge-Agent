"""Persistent chat sessions, each with its own isolated workspace directory."""
import json
import os
import secrets
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import config


@dataclass
class Session:
    id: str
    title: str = "New session"
    model: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)  # {prompt_tokens, completion_tokens, total_tokens, cost}
    allowed_commands: list[str] = field(default_factory=list)  # approved "always" in ask-mode

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Session":
        return Session(
            id=d["id"], title=d.get("title", "New session"),
            model=d.get("model", ""), created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0), messages=d.get("messages", []),
            usage=d.get("usage", {}) or {},
            allowed_commands=d.get("allowed_commands", []) or [],
        )


class SessionStore:
    def __init__(self) -> None:
        config.ensure_dirs()

    # -- paths --------------------------------------------------------------
    def _path(self, sid: str) -> Path:
        safe = "".join(c for c in sid if c.isalnum() or c in "-_")
        return config.SESSIONS_DIR / f"{safe}.json"

    def workspace(self, sid: str) -> Path:
        # Nếu phiên được "mở" vào một dự án thật (pointer file), dùng thư mục đó.
        ptr = config.WORKSPACES_DIR / f"{sid}.path"
        if ptr.exists():
            try:
                target = Path(ptr.read_text(encoding="utf-8").strip())
                if target.is_dir():
                    return target
            except Exception:
                pass
        ws = config.WORKSPACES_DIR / sid
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    def open_workspace(self, sid: str, path: str) -> Path:
        """Trỏ workspace của phiên tới một thư mục có thật (project thật)."""
        target = Path(path).expanduser().resolve()
        if not target.is_dir():
            raise ValueError(f"Thư mục không tồn tại: {path}")
        config.ensure_dirs()
        ptr = config.WORKSPACES_DIR / f"{sid}.path"
        ptr.write_text(str(target), encoding="utf-8")
        return target

    def close_workspace(self, sid: str) -> None:
        ptr = config.WORKSPACES_DIR / f"{sid}.path"
        if ptr.exists():
            ptr.unlink()

    # -- CRUD ---------------------------------------------------------------
    def create(self, model: str = "", title: str = "New session") -> Session:
        sid = time.strftime("%Y%m%d") + "-" + secrets.token_hex(4)
        s = Session(id=sid, title=title, model=model or config.get_model())
        self.save(s)
        return s

    def fork(self, sid: str) -> "Session | None":
        """🍴 Nhân bản phiên (Codex-style fork): copy messages, workspace riêng.

        - Workspace mặc định → copytree (bỏ node_modules/.git/...).
        - Phiên "mở" vào dự án thật (pointer) → fork dùng chung pointer đó.
        """
        import copy
        import shutil
        src = self.get(sid)
        if src is None:
            return None
        ns = self.create(model=src.model, title=(src.title[:56] + " 🍴"))
        ns.messages = copy.deepcopy(src.messages)
        ns.allowed_commands = list(src.allowed_commands)
        self.save(ns)
        # workspace
        ptr = config.WORKSPACES_DIR / f"{sid}.path"
        if ptr.exists():  # phiên trỏ tới dự án thật → fork trỏ chung
            try:
                (config.WORKSPACES_DIR / f"{ns.id}.path").write_text(
                    ptr.read_text(encoding="utf-8"), encoding="utf-8")
                return ns
            except OSError:
                pass
        src_ws = self.workspace(sid)
        dst_ws = config.WORKSPACES_DIR / ns.id
        if src_ws.exists():
            shutil.copytree(
                src_ws, dst_ws,
                ignore=shutil.ignore_patterns(
                    "node_modules", ".git", ".venv", "venv", "__pycache__",
                    "dist", "build", "target", ".next", ".cache"),
                dirs_exist_ok=True)
        return ns


    def get(self, sid: str) -> Session | None:
        p = self._path(sid)
        if not p.exists():
            return None
        try:
            return Session.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            return None

    def list(self) -> list[dict]:
        out = []
        for p in sorted(config.SESSIONS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                out.append({
                    "id": d["id"], "title": d.get("title", "New session"),
                    "model": d.get("model", ""), "updated_at": d.get("updated_at", 0),
                    "message_count": len(d.get("messages", [])),
                    "usage": d.get("usage", {}) or {},
                })
            except Exception:
                continue
        return out

    def save(self, s: Session) -> None:
        config.ensure_dirs()
        s.updated_at = time.time()
        tmp = self._path(s.id).with_suffix(".tmp")
        # encoding="utf-8" là BẮT BUỘC: mặc định theo locale Windows (charmap)
        # sẽ làm sập khi lưu tin nhắn tiếng Việt
        tmp.write_text(json.dumps(s.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self._path(s.id))

    def delete(self, sid: str) -> bool:
        p = self._path(sid)
        if p.exists():
            p.unlink()
            return True
        return False
