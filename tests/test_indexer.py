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
from src.models.jira_models import JiraTasksPage
from src.models.request_models import IndexResult
from src.repositories.ticket_repository import TicketRepository
from src.routers.general import GeneralRouter
from src.clients.lm_client import LMClient


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
    jira.get_tasks.return_value = JiraTasksPage(count=1, jql="project = PROJ", tasks=[
        {"key": "PROJ-1", "description": "problem", "status": "Open",
         "updated_at": "2026-09-17T10:00:00Z", "comments": []}
    ])
    embedder = Mock(version="v1")
    embedder.embed_texts.return_value = [[1.0, 0.0]]
    vespa = MemoryVespa()
    repository = TicketRepository(vespa, embedder)
    config = JiraConfig(jira_url="https://jira.test", base_url="http://manager")
    vectorizer = IncidentVectorizer(jira, repository, config, RuntimeConfig(lock_file=tmp_path / "index.lock"))
    return vectorizer, jira, embedder, vespa


def test_first_repeat_metadata_text_and_model(pipeline):
    vectorizer, jira, embedder, vespa = pipeline
    assert vectorizer.run() == IndexResult(processed=1, changed=1)
    assert vectorizer.run() == IndexResult(processed=1)
    assert embedder.embed_texts.call_count == 1
    assert jira.get_tasks.call_args.args[0] == vectorizer.config.jql
    jira.get_tasks.return_value.tasks[0]["status"] = "Closed"
    assert vectorizer.run().changed == 1
    assert embedder.embed_texts.call_count == 1
    jira.get_tasks.return_value.tasks[0]["description"] = "changed"
    assert vectorizer.run().changed == 1
    embedder.version = "v2"
    assert vectorizer.run().changed == 1
    assert embedder.embed_texts.call_count == 3
    assert "updated >=" not in jira.get_tasks.call_args.args[0]
    assert len(vespa.docs) == 1


@pytest.mark.parametrize("failure", ["jira", "embedder", "vespa"])
def test_failure_preserves_document_and_retries(pipeline, failure):
    vectorizer, jira, embedder, vespa = pipeline
    vectorizer.run()
    before = deepcopy(vespa.docs)
    jira.get_tasks.return_value.tasks[0]["updated_at"] = datetime(2026, 9, 18, tzinfo=timezone.utc)
    jira.get_tasks.return_value.tasks[0]["description"] = "new"
    if failure == "jira":
        jira.get_tasks.return_value.tasks[0].pop("comments")
    elif failure == "embedder":
        embedder.embed_texts.side_effect = RuntimeError()
    else:
        vespa.fail = True
    result = vectorizer.run()
    assert result.failed == 1
    assert vespa.docs == before
    jira.get_tasks.return_value.tasks[0]["comments"] = []
    embedder.embed_texts.side_effect = None
    vespa.fail = False
    assert vectorizer.run().changed == 1


def test_partial_failure_does_not_skip_older_ticket(pipeline):
    vectorizer, jira, _, vespa = pipeline
    issue = jira.get_tasks.return_value.tasks[0]
    jira.get_tasks.return_value.tasks = [{"key": "PROJ-0"}, issue]
    result = vectorizer.run()
    assert (result.failed, result.changed) == (1, 1)
    assert all(schema == "incident" for schema, _ in vespa.docs)
    assert "updated >=" not in jira.get_tasks.call_args.args[0]


def test_search_failure_preserves_documents_and_retries(pipeline):
    vectorizer, jira, _, vespa = pipeline
    vectorizer.run()
    before = deepcopy(vespa.docs)
    jira.get_tasks.side_effect = RuntimeError("manager failure")
    with pytest.raises(RuntimeError):
        vectorizer.run()
    assert vespa.docs == before
    jira.get_tasks.side_effect = None
    assert vectorizer.run().changed == 0


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
        response = client.post("/api/v1/index")
        assert response.json() == {"processed": 1, "changed": 1, "failed": 0}
        with index_lock(vectorizer.runtime.lock_file):
            assert client.post("/api/v1/index", json={}).status_code == 409
        vectorizer.repository.vespa.ready = Mock(side_effect=RuntimeError())
        assert client.get("/api/v1/ready").status_code == 503
        assert client.post("/api/v1/index", json={}).status_code == 502


@pytest.mark.parametrize("data", [[], [{"index": 0, "embedding": [1]}], [{"index": 1, "embedding": [1, 2]}], [{"index": 0, "embedding": ["bad", 0]}]])
def test_embedder_rejects_invalid_response(data):
    service = LMClient(EmbedderConfig(dimensions=2))
    service.client.close()
    service.client = httpx.Client(base_url="http://embedder/v1/", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": data})))
    try:
        with pytest.raises(DependencyError):
            service.embed_texts(["text"])
    finally:
        service.close()


def test_embedder_orders_and_batches():
    service = LMClient(EmbedderConfig(dimensions=2, batch_size=2, prefix="passage: "))
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


def test_force_reembeds_unchanged_tickets_and_preserves_on_failure(pipeline):
    vectorizer, jira, embedder, vespa = pipeline
    assert vectorizer.run().changed == 1
    assert vectorizer.run().changed == 0
    embedder.embed_texts.return_value = [[0.0, 1.0]]
    assert vectorizer.run(force=True) == IndexResult(processed=1, changed=1)
    assert embedder.embed_texts.call_count == 2
    assert vespa.docs["incident", "PROJ-1"]["embedding"] == {"values": [0.0, 1.0]}
    assert jira.get_tasks.call_args.args[0] == vectorizer.config.jql
    before = deepcopy(vespa.docs)
    embedder.embed_texts.side_effect = RuntimeError()
    assert vectorizer.run(force=True).failed == 1
    assert vespa.docs == before


def test_url_change_reuses_embedding(pipeline):
    vectorizer, jira, embedder, vespa = pipeline
    vectorizer.run()
    assert vespa.docs["incident", "PROJ-1"]["url"] == "https://jira.test/browse/PROJ-1"
    vectorizer.config.jira_url = "https://jira.test/jira/"
    assert vectorizer.run().changed == 1
    assert vespa.docs["incident", "PROJ-1"]["url"] == "https://jira.test/jira/browse/PROJ-1"
    assert embedder.embed_texts.call_count == 1
