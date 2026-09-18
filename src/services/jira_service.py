from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

import httpx

from src.models.jira_models import JiraComment, JiraCommentPage, JiraIssue, JiraSearchPage


class JiraService:
    def __init__(self, base_url: str, token: str, *, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=timeout,
        )

    def __enter__(self) -> JiraService:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get_issue_raw(self, key: str) -> dict[str, Any]:
        response = self._client.get(
            f"/rest/api/2/issue/{key}", params={"fields": "description,status,updated"}
        )
        response.raise_for_status()
        return response.json()

    def get_issue(self, key: str) -> JiraIssue:
        return JiraIssue.model_validate(self.get_issue_raw(key))

    def iter_comment_pages_raw(self, key: str, page_size: int = 100) -> Iterator[dict[str, Any]]:
        start_at = 0
        while True:
            response = self._client.get(
                f"/rest/api/2/issue/{key}/comment",
                params={"startAt": start_at, "maxResults": page_size},
            )
            response.raise_for_status()
            raw: dict[str, Any] = response.json()
            yield raw
            page = JiraCommentPage.model_validate(raw)
            consumed = len(page.comments)
            start_at += consumed
            if consumed == 0 or start_at >= page.total:
                break

    def get_comments(self, key: str, page_size: int = 100) -> list[JiraComment]:
        comments: list[JiraComment] = []
        for raw in self.iter_comment_pages_raw(key, page_size):
            comments.extend(JiraCommentPage.model_validate(raw).comments)
        return comments

    def iter_issue_keys(self, jql: str, page_size: int = 100) -> Iterator[str]:
        start_at = 0
        while True:
            response = self._client.get(
                "/rest/api/2/search",
                params={
                    "jql": jql,
                    "fields": "key",
                    "startAt": start_at,
                    "maxResults": page_size,
                },
            )
            response.raise_for_status()
            page = JiraSearchPage.model_validate(response.json())
            for issue in page.issues:
                yield issue.key
            consumed = len(page.issues)
            start_at += consumed
            if consumed == 0 or start_at >= page.total:
                break


def jql_with_updated_since(base_jql: str, since: datetime | None) -> str:
    if since is None:
        return base_jql
    value = since.strftime("%Y-%m-%d %H:%M")
    order_marker = " order by "
    lower = base_jql.lower()
    position = lower.rfind(order_marker)
    if position >= 0:
        query, ordering = base_jql[:position], base_jql[position:]
    else:
        query, ordering = base_jql, ""
    return f"({query.strip()}) AND updated >= '{value}'{ordering}"
