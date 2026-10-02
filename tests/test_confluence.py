from copy import deepcopy
import hashlib
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from src import cli
from src.application import Application
from src.common.config import ConfluenceConfig, EmbedderConfig, RuntimeConfig
from src.common.errors import IndexAlreadyRunning
from src.common.locking import index_lock
from src.core.confluence_vectorizer import ConfluenceVectorizer
from src.models.confluence_models import ConfluenceRecordsPage
from src.models.request_models import IndexResult
from src.repositories.confluence_page_repository import ConfluencePageRepository
from src.services.confluence_service import ConfluenceService
from test_indexer import MemoryVespa


def page(records):
    return ConfluenceRecordsPage(count=len(records), content_type="page", body_format="text", records=records)


@pytest.mark.parametrize("space", [None, "DOCS"])
def test_service_contract(space):
    service = ConfluenceService(ConfluenceConfig(base_url="http://manager", space_key=space))
    def handle(request):
        assert request.url.path == "/api/v1/confluence/records"
        expected = {"content_type": "page", "body_format": "text", "page_size": "100"}
        if space:
            expected["space_key"] = space
        assert dict(request.url.params) == expected
        assert "authorization" not in request.headers
        assert request.extensions["timeout"]["read"] == 120
        return httpx.Response(200, json=page([{"id": "1", "body": None}]).model_dump())
    timeout = service.client.timeout
    service.client.close()
    service.client = httpx.Client(base_url="http://manager", timeout=timeout, transport=httpx.MockTransport(handle))
    try:
        assert service.get_records().records == [{"id": "1", "body": None}]
    finally:
        service.close()


@pytest.fixture
def pipeline(tmp_path):
    source = Mock()
    source.get_records.return_value = page([{"id": "42", "body": "  Main\r\ntext! \n", "updated_at": "2026-09-30T12:00:00Z"}])
    embedder = Mock(version="v1")
    embedder.embed_texts.return_value = [[1.0] + [0.0] * 2047]
    vespa = MemoryVespa()
    vectorizer = ConfluenceVectorizer(source, ConfluencePageRepository(vespa, embedder), RuntimeConfig(lock_file=tmp_path / "index.lock"))
    return vectorizer, source, embedder, vespa


def test_mapping_repeat_metadata_text_model(pipeline):
    vectorizer, source, embedder, vespa = pipeline
    assert EmbedderConfig(_env_file=None).dimensions == 2048
    assert vectorizer.run() == IndexResult(processed=1, changed=1)
    record = source.get_records.return_value.records[0]
    stored = vespa.docs["confluence_page", "42"]
    assert stored["text"] == record["body"]
    assert stored["page_id"] == "42"
    assert stored["content_hash"] == hashlib.sha256(record["body"].encode()).hexdigest()
    assert stored["updated_at_confluence"] == "2026-09-30T12:00:00+00:00"
    before = deepcopy(vespa.docs)
    assert vectorizer.run() == IndexResult(processed=1)
    assert vespa.docs == before
    record["updated_at"] = None
    assert vectorizer.run().changed == 1
    assert vespa.docs["confluence_page", "42"]["updated_at_confluence"] == ""
    assert embedder.embed_texts.call_count == 1
    record["body"] = "new"
    assert vectorizer.run().changed == 1
    embedder.version = "v2"
    assert vectorizer.run().changed == 1
    assert embedder.embed_texts.call_count == 3
    assert len(vespa.docs) == 1


@pytest.mark.parametrize("body", [None, "", " \n"])
def test_empty_body_preserves_document_and_continues(pipeline, body):
    vectorizer, source, _, vespa = pipeline
    vectorizer.run()
    before = deepcopy(vespa.docs["confluence_page", "42"])
    source.get_records.return_value = page([{"id": "42", "body": body}, {"id": "43", "body": "valid"}])
    assert vectorizer.run() == IndexResult(processed=2, changed=1, failed=1)
    assert vespa.docs["confluence_page", "42"] == before


def test_invalid_record_and_embedding_failure(pipeline):
    vectorizer, source, embedder, vespa = pipeline
    vectorizer.run()
    before = deepcopy(vespa.docs)
    source.get_records.return_value = page([{"body": "missing id"}, {"id": "42", "body": "changed"}])
    embedder.embed_texts.side_effect = RuntimeError()
    assert vectorizer.run().failed == 2
    assert vespa.docs == before


def test_empty_upstream_failure_and_lock(pipeline):
    vectorizer, source, _, _ = pipeline
    source.get_records.return_value = page([])
    assert vectorizer.run() == IndexResult()
    with index_lock(vectorizer.runtime.lock_file):
        with pytest.raises(IndexAlreadyRunning):
            vectorizer.run()
    source.get_records.side_effect = httpx.ReadTimeout("timeout")
    with pytest.raises(httpx.ReadTimeout):
        vectorizer.run()
    source.get_records.side_effect = None
    assert vectorizer.run() == IndexResult()


def test_http_lazy_resolution_and_statuses(pipeline):
    vectorizer, source, _, vespa = pipeline
    container = Mock()
    container.get.side_effect = lambda cls: vectorizer if cls is ConfluenceVectorizer else Mock()
    app = Application(container).start_app()
    assert all(call.args[0] is not ConfluenceVectorizer for call in container.get.call_args_list)
    with TestClient(app) as client:
        assert client.post("/api/v1/index/confluence").json()["changed"] == 1
        source.get_records.return_value = page([{"id": "42", "body": None}])
        response = client.post("/api/v1/index/confluence")
        assert response.status_code == 200 and response.json()["failed"] == 1
        with index_lock(vectorizer.runtime.lock_file):
            assert client.post("/api/v1/index/confluence").status_code == 409
        source.get_records.side_effect = RuntimeError("secret")
        response = client.post("/api/v1/index/confluence")
        assert response.status_code == 502 and "secret" not in response.text
    container.close.assert_called_once()


@pytest.mark.parametrize("failed,error,code", [(0, False, 0), (1, False, 1), (0, True, 1)])
def test_cli(monkeypatch, failed, error, code):
    container = Mock()
    container.get.return_value.run.return_value = IndexResult(processed=1, failed=failed)
    if error:
        container.get.return_value.run.side_effect = RuntimeError()
    monkeypatch.setattr(cli, "initialize_container", lambda: container)
    monkeypatch.setattr("sys.argv", ["confluence-index"])
    with pytest.raises(SystemExit) as exc:
        cli.confluence_index_main()
    assert exc.value.code == code
    container.get.assert_called_once_with(ConfluenceVectorizer)
    container.close.assert_called_once()


@pytest.mark.parametrize("mode", ["found", "missing", "error"])
def test_dump_raw_page(monkeypatch, capsys, mode):
    import json
    import src.services.confluence_service as module
    record = {"id": "42", "title": "Название", "body": "  Text\n", "body_format": "text", "url": "https://confluence/page/42"}
    service = Mock()
    service.get_records.return_value = page([{"id": "other"}, record] if mode == "found" else [])
    if mode == "error":
        service.get_records.side_effect = RuntimeError("private response")
    monkeypatch.setenv("CONFLUENCE_INDEXER_BASE_URL", "http://manager")
    monkeypatch.setattr(module, "ConfluenceService", lambda config: service)
    monkeypatch.setattr("sys.argv", ["confluence-dump", "42"])
    if mode == "found":
        cli.confluence_dump_main()
        assert json.loads(capsys.readouterr().out) == record
    else:
        with pytest.raises(SystemExit) as exc:
            cli.confluence_dump_main()
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert not captured.out and captured.err
        assert "private response" not in captured.err
    service.close.assert_called_once()


def test_force_reembeds_unchanged_pages_and_preserves_on_failure(pipeline):
    vectorizer, source, embedder, vespa = pipeline
    assert vectorizer.run().changed == 1
    assert vectorizer.run().changed == 0
    vector = [0.0, 1.0] + [0.0] * 2046
    embedder.embed_texts.return_value = [vector]
    assert vectorizer.run(force=True) == IndexResult(processed=1, changed=1)
    assert embedder.embed_texts.call_count == 2
    assert vespa.docs["confluence_page", "42"]["embedding"] == {"values": vector}
    before = deepcopy(vespa.docs)
    embedder.embed_texts.side_effect = RuntimeError()
    assert vectorizer.run(force=True).failed == 1
    assert vespa.docs == before
