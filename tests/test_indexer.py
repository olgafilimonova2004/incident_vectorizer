from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.common.config import EmbedderConfig, JiraConfig, RuntimeConfig
from src.common.errors import DependencyError, IndexAlreadyRunning
from src.common.locking import index_lock
from src.core.incident_vectorizer import IncidentVectorizer
from src.models.jira_models import JiraIssue
from src.models.request_models import IndexResult
from src.repositories.ticket_repository import TicketRepository
from src.routers.general import GeneralRouter
from src.services.embedder_service import EmbedderService


class MemoryVespa:
    def __init__(self):
        self.docs = {}
        self.fail = False

    def ready(self):
        pass

    def get(self, schema, key):
        return deepcopy(self.docs.get((schema, key)))

    def put(self, schema, key, fields):
        if self.fail and schema == "incident":
            raise RuntimeError("write failure")
        self.docs[schema, key] = deepcopy(fields)


@pytest.fixture
def pipeline(tmp_path):
    jira = Mock()
    jira.iter_issue_keys.return_value = ["PROJ-1"]
    jira.get_issue.return_value = JiraIssue.model_validate({"key": "PROJ-1", "fields": {"description": "problem", "status": {"name": "Open"}, "updated": "2026-09-17T10:00:00Z"}})
    jira.get_comments.return_value = []
    embedder = Mock(version="v1")
    embedder.embed_texts.return_value = [[1.0, 0.0]]
    vespa = MemoryVespa()
    repository = TicketRepository(vespa, embedder)
    config = JiraConfig(jira_url="https://jira.test", jira_token="secret")
    vectorizer = IncidentVectorizer(jira, repository, config, RuntimeConfig(lock_file=tmp_path / "index.lock"))
    return vectorizer, jira, embedder, vespa


def test_first_repeat_metadata_text_and_model(pipeline):
    vectorizer, jira, embedder, vespa = pipeline
    assert vectorizer.run() == IndexResult(processed=1, changed=1, checkpoint_advanced=True)
    assert vectorizer.run() == IndexResult(processed=1)
    assert embedder.embed_texts.call_count == 1
    assert "updated >= '2026-09-17 09:55'" in jira.iter_issue_keys.call_args.args[0]
    jira.get_issue.return_value.fields.status.name = "Closed"
    assert vectorizer.run().changed == 1
    assert embedder.embed_texts.call_count == 1
    jira.get_issue.return_value.fields.description = "changed"
    assert vectorizer.run().changed == 1
    embedder.version = "v2"
    assert vectorizer.run(full=True).changed == 1
    assert embedder.embed_texts.call_count == 3
    assert "updated >=" not in jira.iter_issue_keys.call_args.args[0]
    assert len(vespa.docs) == 2


@pytest.mark.parametrize("failure", ["jira", "embedder", "vespa"])
def test_failure_preserves_checkpoint_and_retries(pipeline, failure):
    vectorizer, jira, embedder, vespa = pipeline
    vectorizer.run()
    before = deepcopy(vespa.docs)
    jira.get_issue.return_value.fields.updated = datetime(2026, 9, 18, tzinfo=timezone.utc)
    jira.get_issue.return_value.fields.description = "new"
    if failure == "jira":
        jira.get_comments.side_effect = RuntimeError()
    elif failure == "embedder":
        embedder.embed_texts.side_effect = RuntimeError()
    else:
        vespa.fail = True
    result = vectorizer.run()
    assert result.failed == 1 and not result.checkpoint_advanced
    assert vespa.docs == before
    jira.get_comments.side_effect = embedder.embed_texts.side_effect = None
    vespa.fail = False
    assert vectorizer.run().checkpoint_advanced


def test_partial_failure_does_not_skip_older_ticket(pipeline):
    vectorizer, jira, _, vespa = pipeline
    jira.iter_issue_keys.return_value = ["PROJ-0", "PROJ-1"]
    issue = jira.get_issue.return_value
    jira.get_issue.side_effect = [RuntimeError(), issue]
    result = vectorizer.run()
    assert (result.failed, result.changed) == (1, 1)
    assert not any(schema == "index_checkpoint" for schema, _ in vespa.docs)
    jira.get_issue.side_effect = None
    vectorizer.run()
    assert "updated >=" not in jira.iter_issue_keys.call_args.args[0]


def test_search_failure_after_success_does_not_checkpoint(pipeline):
    vectorizer, jira, _, vespa = pipeline
    def keys(*args):
        yield "PROJ-1"
        raise RuntimeError("page failure")
    jira.iter_issue_keys.side_effect = keys
    with pytest.raises(RuntimeError):
        vectorizer.run()
    assert not any(schema == "index_checkpoint" for schema, _ in vespa.docs)


def test_lock_rejects_parallel_run_and_releases(pipeline):
    vectorizer, *_ = pipeline
    with index_lock(vectorizer.runtime.lock_file):
        with pytest.raises(IndexAlreadyRunning):
            vectorizer.run()
    assert vectorizer.run().changed == 1


def test_http_statuses(pipeline):
    vectorizer, *_ = pipeline
    app = FastAPI()
    router = GeneralRouter(vectorizer, vectorizer.repository.vespa)
    app.include_router(router.router, prefix=router.prefix)
    with TestClient(app) as client:
        assert client.get("/api/v1/ping").json() == "pong"
        assert client.get("/api/v1/ready").status_code == 200
        assert client.post("/api/v1/index", json={}).json()["changed"] == 1
        with index_lock(vectorizer.runtime.lock_file):
            assert client.post("/api/v1/index", json={}).status_code == 409
        vectorizer.repository.vespa.ready = Mock(side_effect=RuntimeError())
        assert client.get("/api/v1/ready").status_code == 503
        assert client.post("/api/v1/index", json={}).status_code == 502


@pytest.mark.parametrize("data", [[], [{"index": 0, "embedding": [1]}], [{"index": 1, "embedding": [1, 2]}], [{"index": 0, "embedding": ["bad", 0]}]])
def test_embedder_rejects_invalid_response(data):
    service = EmbedderService(EmbedderConfig(dimensions=2))
    service.client.close()
    service.client = httpx.Client(base_url="http://embedder/v1/", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": data})))
    try:
        with pytest.raises(DependencyError):
            service.embed_texts(["text"])
    finally:
        service.close()


def test_embedder_orders_and_batches():
    service = EmbedderService(EmbedderConfig(dimensions=2, batch_size=2))
    requests = []
    def handle(request):
        import json
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [i, 1]} for i in reversed(range(len(payload["input"])))]})
    service.client.close()
    service.client = httpx.Client(base_url="http://embedder/v1/", transport=httpx.MockTransport(handle))
    try:
        assert service.embed_texts(["a", "b", "c"]) == [[0, 1], [1, 1], [0, 1]]
        assert requests[0]["input"] == ["passage: a", "passage: b"]
    finally:
        service.close()
