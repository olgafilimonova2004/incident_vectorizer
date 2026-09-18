from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class JiraStatus(BaseModel):
    name: str = ""


class JiraIssueFields(BaseModel):
    description: str | None = None
    status: JiraStatus = Field(default_factory=JiraStatus)
    updated: datetime


class JiraIssue(BaseModel):
    key: str
    fields: JiraIssueFields


class JiraAuthor(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    display_name: str = Field(default="Неизвестный автор", alias="displayName")


class JiraComment(BaseModel):
    id: str
    author: JiraAuthor = Field(default_factory=JiraAuthor)
    body: str | None = None
    created: datetime


class JiraCommentPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    start_at: int = Field(alias="startAt")
    max_results: int = Field(alias="maxResults")
    total: int
    comments: list[JiraComment] = Field(default_factory=list)


class JiraSearchIssue(BaseModel):
    key: str


class JiraSearchPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    start_at: int = Field(alias="startAt")
    max_results: int = Field(alias="maxResults")
    total: int
    issues: list[JiraSearchIssue] = Field(default_factory=list)


class TicketDocument(BaseModel):
    ticket_id: str
    text: str
    status: str
    updated_at_jira: datetime
    content_hash: str
