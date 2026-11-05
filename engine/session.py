"""Persistent chat sessions, each with its own isolated workspace directory."""
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
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
    owner_id: str = ""  # "" = legacy/local; multi-user API luôn gán user.id

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
            owner_id=d.get("owner_id", "") or "",
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
    def create(self, model: str = "", title: str = "New session", owner_id: str = "") -> Session:
        sid = time.strftime("%Y%m%d") + "-" + secrets.token_hex(4)
        s = Session(id=sid, title=title, model=model or config.get_model(), owner_id=owner_id)
        self.save(s)
        return s

    def fork(self, sid: str, owner_id: str | None = None) -> "Session | None":
        """🍴 Nhân bản phiên (Codex-style fork): copy messages, workspace riêng.

        - Workspace mặc định → copytree (bỏ node_modules/.git/...).
        - Phiên "mở" vào dự án thật (pointer) → fork dùng chung pointer đó.
        """
        import copy
        import shutil
        src = self.get(sid)
        if src is None:
            return None
        ns = self.create(model=src.model, title=(src.title[:56] + " 🍴"),
                         owner_id=src.owner_id if owner_id is None else owner_id)
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
        try:
            from . import worktree as fwt
            if fwt.export_tree_sync(sid, dst_ws):  # B2: fork từ snapshot (nhanh, nhất quán)
                return ns
        except Exception:  # noqa: BLE001 — archive lỗi → copytree như cũ
            pass
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

    def list(self, q: str = "", owner_id: str | None = None) -> list[dict]:
        """Danh sách phiên mới nhất trước. q ≠ '' → lọc theo tiêu đề NỘI DUNG tin nhắn."""
        out = []
        ql = (q or "").strip().lower()
        for p in sorted(config.SESSIONS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                raw = p.read_text(encoding="utf-8")
                if ql and ql not in raw.lower():
                    continue
                d = json.loads(raw)
                if owner_id is not None and (d.get("owner_id", "") or "") != owner_id:
                    continue
                out.append({
                    "id": d["id"], "title": d.get("title", "New session"),
                    "model": d.get("model", ""), "updated_at": d.get("updated_at", 0),
                    "message_count": len(d.get("messages", [])),
                    "usage": d.get("usage", {}) or {},
                })
            except Exception:
                continue
        return out

    def rename(self, sid: str, title: str) -> bool:
        """Đổi tiêu đề phiên (≤80 ký tự). False nếu phiên không tồn tại."""
        s_ = self.get(sid)
        if not s_:
            return False
        t = (title or "").strip()[:80]
        if t:
            s_.title = t
            self.save(s_)
        return True

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


class ScopedSessionStore:
    """ACL wrapper: mọi thao tác chỉ chạm session thuộc đúng một user.

    Không có ``__getattr__`` delegation — method mới phải được xem xét ACL tường minh.
    Session legacy (owner_id="") vô hình với tài khoản multi-user cho tới khi admin migrate.
    """

    def __init__(self, base: SessionStore, user_id: str, *, allow_mcp: bool = True) -> None:
        if not user_id:
            raise ValueError("ScopedSessionStore cần user_id")
        self.base = base
        self.user_id = user_id
        self.allow_mcp = allow_mcp

    def create(self, model: str = "", title: str = "New session") -> Session:
        return self.base.create(model=model, title=title, owner_id=self.user_id)

    def get(self, sid: str) -> Session | None:
        session = self.base.get(sid)
        return session if session and session.owner_id == self.user_id else None

    def save(self, session: Session) -> None:
        if session.owner_id != self.user_id:
            raise PermissionError("Không được ghi session của user khác")
        self.base.save(session)

    def list(self, q: str = "") -> list[dict]:
        return self.base.list(q=q, owner_id=self.user_id)

    def workspace(self, sid: str) -> Path:
        if self.get(sid) is None:
            raise ValueError("Session not found")
        return self.base.workspace(sid)

    def fork(self, sid: str) -> Session | None:
        if self.get(sid) is None:
            return None
        return self.base.fork(sid, owner_id=self.user_id)

    def rename(self, sid: str, title: str) -> bool:
        return False if self.get(sid) is None else self.base.rename(sid, title)

    def delete(self, sid: str) -> bool:
        return False if self.get(sid) is None else self.base.delete(sid)

    def open_workspace(self, sid: str, path: str) -> Path:
        if self.get(sid) is None:
            raise ValueError("Session not found")
        return self.base.open_workspace(sid, path)

    def close_workspace(self, sid: str) -> None:
        if self.get(sid) is not None:
            self.base.close_workspace(sid)
