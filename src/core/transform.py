from __future__ import annotations

import hashlib
import re

from src.models.jira_models import JiraComment, JiraIssue, TicketDocument


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"![^\s!]+!", "", value)
    return "\n".join(line.rstrip() for line in value.split("\n")).strip()


def build_document(issue: JiraIssue, comments: list[JiraComment]) -> TicketDocument:
    lines = ["Описание:", normalize_text(issue.fields.description), "", "Комментарии:"]
    for comment in sorted(comments, key=lambda item: (item.created, item.id)):
        created = comment.created.isoformat()
        author = normalize_text(comment.author.display_name) or "Неизвестный автор"
        body = normalize_text(comment.body)
        lines.append(f"[{created}] {author}: {body}")

    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"
    return TicketDocument(
        ticket_id=issue.key,
        text=text,
        status=normalize_text(issue.fields.status.name),
        updated_at_jira=issue.fields.updated,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
