import httpx
import pytest
from pydantic import ValidationError

from src.clients.jira_client import JiraClient
from src.common.config import JiraConfig
from src.models.jira_models import JiraIssue


def test_manager_contract():
    requests = []
    def handle(request):
        requests.append(request)
        assert request.url.path == "/api/v1/jira/tasks"
        assert dict(request.url.params) == {"jql": "project = P", "page_size": "10"}
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"count": 1, "jql": "project = P", "tasks": [
            {"key": "P-1", "updated_at": "2026-09-17T10:00:00Z", "comments": []}
        ]})
    with JiraClient(JiraConfig(base_url="http://manager", jira_url="http://jira")) as client:
        client._client.close()
        client._client = httpx.Client(base_url="http://manager", transport=httpx.MockTransport(handle))
        page = client.get_tasks("project = P", 10)
    assert JiraIssue.model_validate(page.tasks[0]).comments == []
    assert len(requests) == 1
    assert client._client.is_closed


def test_comments_are_required():
    with pytest.raises(ValidationError):
        JiraIssue.model_validate({"key": "P-1", "updated_at": "2026-09-17T10:00:00Z"})
