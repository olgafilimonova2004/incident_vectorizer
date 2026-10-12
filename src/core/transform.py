from __future__ import annotations

import hashlib
import re

from src.models.jira_models import JiraIssue, TicketDocument


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    # Protect code contents from wiki formatting substitutions.
    code: list[str] = []

    def keep_code(match: re.Match[str]) -> str:
        code.append(match.group(1).strip("\n"))
        return f"\x00CODE{len(code) - 1}\x00"

    value = re.sub(r"\{code(?::[^}]+)?\}(.*?)\{code\}", keep_code, value, flags=re.S)
    value = re.sub(r"\{noformat\}(.*?)\{noformat\}", keep_code, value, flags=re.S)
    value = re.sub(r"\{\{(.*?)\}\}", keep_code, value, flags=re.S)
    value = re.sub(r"![^!\n]+!", "", value)
    value = re.sub(r"\[([^]\n|]+)\|([^]\n]+)\]", r"\1 (\2)", value)
    value = re.sub(r"\[(?:~|\^)([^]\n]+)\]", r"\1", value)
    value = re.sub(r"\[((?:https?://|mailto:)[^]\n]+)\]", r"\1", value)
    value = re.sub(r"(?m)^\s*(?:h[1-6]\.|bq\.)\s+", "", value)
    value = re.sub(r"(?m)^\s*[*#]+\s+", "• ", value)
    value = re.sub(r"\{(?:color|panel)(?::[^}]*)?\}|\{quote\}", "", value)
    value = value.replace(r"\\", "\n")
    # Only paired markers at word boundaries are formatting (keep a_b and x*y).
    for marker in ("*", "_", "+", "-", "^", "~", "??"):
        escaped = re.escape(marker)
        value = re.sub(rf"(?<!\w){escaped}(\S(?:.*?\S)?){escaped}(?!\w)", r"\1", value)
    lines = []
    for line in value.split("\n"):
        if line.strip().startswith("|") and line.rstrip().endswith("|"):
            line = " ".join(cell.strip() for cell in re.split(r"\|+", line.strip().strip("|")))
        lines.append(line.rstrip())
    value = "\n".join(lines).strip()
    for index, content in enumerate(code):
        value = value.replace(f"\x00CODE{index}\x00", content)
    return value


def build_document(issue: JiraIssue, *, url: str = "") -> TicketDocument:
    lines = ["Описание:", normalize_text(issue.description), "", "Комментарии:"]
    for comment in sorted(issue.comments, key=lambda item: (item.created, item.id)):
        created = comment.created.isoformat()
        author = normalize_text(comment.author) or "Неизвестный автор"
        body = normalize_text(comment.body)
        lines.append(f"[{created}] {author}: {body}")

    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"
    return TicketDocument(
        ticket_id=issue.key,
        url=url,
        text=text,
        status=normalize_text(issue.status),
        updated_at_jira=issue.updated_at,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
