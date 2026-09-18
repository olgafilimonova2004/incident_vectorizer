import httpx

from src.services.jira_service import JiraService
from src.services.jira_service import jql_with_updated_since
from datetime import datetime, timezone


def test_loads_all_comment_pages() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        start = int(request.url.params["startAt"])
        comments = [
            {"id": str(start), "body": None, "created": "2026-09-17T10:00:00Z"}
        ]
        return httpx.Response(200, json={"startAt": start, "maxResults": 1, "total": 3, "comments": comments})

    service = JiraService("https://jira.test", "secret")
    service._client = httpx.Client(
        base_url="https://jira.test",
        headers={"Authorization": "Bearer secret"},
        transport=httpx.MockTransport(handler),
    )
    try:
        comments = service.get_comments("PROJ-1", page_size=1)
    finally:
        service.close()
    assert [comment.id for comment in comments] == ["0", "1", "2"]
    assert all(request.headers["Authorization"] == "Bearer secret" for request in requests)


def test_search_pagination_and_empty_page():
    starts = []
    def handle(request):
        start = int(request.url.params["startAt"])
        starts.append(start)
        return httpx.Response(200, json={"startAt": start, "maxResults": 1, "total": 5, "issues": [{"key": f"P-{start}"}] if start < 2 else []})
    service = JiraService("https://jira.test", "secret")
    service.close()
    service._client = httpx.Client(base_url="https://jira.test", transport=httpx.MockTransport(handle))
    try:
        assert list(service.iter_issue_keys("project = P", 1)) == ["P-0", "P-1"]
        assert starts == [0, 1, 2]
    finally:
        service.close()


def test_jql_preserves_ordering_and_no_checkpoint():
    query = "project = P OR project = Q ORDER BY updated ASC"
    assert jql_with_updated_since(query, None) == query
    assert jql_with_updated_since(query, datetime(2026, 9, 18, tzinfo=timezone.utc)) == "(project = P OR project = Q) AND updated >= '2026-09-18 00:00' ORDER BY updated ASC"
