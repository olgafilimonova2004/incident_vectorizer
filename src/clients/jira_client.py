from __future__ import annotations

import httpx

from src.common.config import JiraConfig
from src.models.jira_models import JiraTasksPage


class JiraClient:
    def __init__(self, config: JiraConfig):
        self._client = httpx.Client(
            base_url=str(config.base_url).rstrip("/"),
            headers={"Accept": "application/json"},
            timeout=config.timeout,
        )

    def __enter__(self) -> JiraClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get_tasks(self, jql: str, page_size: int = 100) -> JiraTasksPage:
        response = self._client.get(
            "/api/v1/jira/tasks", params={"jql": jql, "page_size": page_size}
        )
        response.raise_for_status()
        return JiraTasksPage.model_validate(response.json())
