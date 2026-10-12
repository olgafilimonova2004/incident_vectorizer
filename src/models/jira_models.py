from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class JiraComment(BaseModel):
    id: str
    author: str | None = None
    body: str | None = None
    created: datetime


class JiraIssue(BaseModel):
    key: str = Field(min_length=1)
    description: str | None = None
    status: str | None = None
    updated_at: datetime | None = None
    comments: list[JiraComment]


class JiraTasksPage(BaseModel):
    count: int
    total: int | None = None
    jql: str
    # Validate records individually so one malformed task does not stop indexing.
    tasks: list[dict[str, Any]]


class TicketDocument(BaseModel):
    ticket_id: str
    url: str = ""
    text: str
    status: str
    updated_at_jira: datetime | None
    content_hash: str
