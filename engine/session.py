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

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Session":
        return Session(
            id=d["id"], title=d.get("title", "New session"),
            model=d.get("model", ""), created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0), messages=d.get("messages", []),
        )


class SessionStore:
    def __init__(self) -> None:
        config.ensure_dirs()

    # -- paths --------------------------------------------------------------
    def _path(self, sid: str) -> Path:
        safe = "".join(c for c in sid if c.isalnum() or c in "-_")
        return config.SESSIONS_DIR / f"{safe}.json"

    def workspace(self, sid: str) -> Path:
        ws = config.WORKSPACES_DIR / sid
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    # -- CRUD ---------------------------------------------------------------
    def create(self, model: str = "", title: str = "New session") -> Session:
        sid = time.strftime("%Y%m%d") + "-" + secrets.token_hex(4)
        s = Session(id=sid, title=title, model=model or config.get_model())
        self.save(s)
        return s

    def get(self, sid: str) -> Session | None:
        p = self._path(sid)
        if not p.exists():
            return None
        try:
            return Session.from_dict(json.loads(p.read_text()))
        except Exception:
            return None

    def list(self) -> list[dict]:
        out = []
        for p in sorted(config.SESSIONS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                d = json.loads(p.read_text())
                out.append({
                    "id": d["id"], "title": d.get("title", "New session"),
                    "model": d.get("model", ""), "updated_at": d.get("updated_at", 0),
                    "message_count": len(d.get("messages", [])),
                })
            except Exception:
                continue
        return out

    def save(self, s: Session) -> None:
        config.ensure_dirs()
        s.updated_at = time.time()
        tmp = self._path(s.id).with_suffix(".tmp")
        tmp.write_text(json.dumps(s.to_dict(), ensure_ascii=False, indent=1))
        os.replace(tmp, self._path(s.id))

    def delete(self, sid: str) -> bool:
        p = self._path(sid)
        if p.exists():
            p.unlink()
            return True
        return False
