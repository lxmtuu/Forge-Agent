"""Export session → Markdown (kiểu /export của Claude Code)."""
import time
from .session import Session


def to_markdown(s: Session) -> str:
    lines = [
        f"# 🗂 {s.title}",
        "",
        f"- **Phiên:** `{s.id}`",
        f"- **Model:** {s.model or '—'}",
        f"- **Tạo:** {time.strftime('%Y-%m-%d %H:%M', time.localtime(s.created_at))}"
        f" · **Xuất:** {time.strftime('%Y-%m-%d %H:%M')}",
        f"- **Tokens:** {(s.usage or {}).get('total_tokens', 0)}",
        "",
        "---",
        "",
    ]
    for m in s.messages:
        role = m.get("role", "?")
        icon = {"user": "🧑", "assistant": "🤖", "tool": "🔧", "system": "⚙"}.get(role, "•")
        label = {"user": "Người dùng", "assistant": "Agent", "tool": "Tool",
                 "system": "System"}.get(role, role)
        lines.append(f"## {icon} {label}")
        lines.append("")
        c = m.get("content")
        if isinstance(c, list):  # content parts (multimodal)
            for part in c:
                if part.get("type") == "text":
                    lines.append(str(part.get("text", "")))
                elif part.get("type") == "image_url":
                    lines.append("_[🖼 ảnh đính kèm]_")
        elif c:
            lines.append(str(c))
        for tc in m.get("tool_calls") or []:
            fn = (tc.get("function") or {})
            lines.append(f"- ⚙ **{fn.get('name')}** `{str(fn.get('arguments'))[:200]}`")
        lines.append("")
    return "\n".join(lines) + "\n"
