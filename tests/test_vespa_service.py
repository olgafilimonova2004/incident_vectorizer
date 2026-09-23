import json
from unittest.mock import Mock

import pytest
from requests import Response
from requests.exceptions import HTTPError
from vespa.application import VespaSync

from src.common.config import VespaConfig
from src.common.errors import DependencyError
from src.services.vespa_service import VespaService


@pytest.fixture
def vespa(monkeypatch):
    service = VespaService(VespaConfig(url="http://vespa:8080", timeout=7))
    send = Mock()
    monkeypatch.setattr(service.client.http_session, "send", send)
    try:
        yield service, send
    finally:
        service.close()


def response(status, payload):
    result = Response()
    result.status_code = status
    result._content = json.dumps(payload).encode()
    result.url = "http://vespa:8080"
    return result


def test_get_uses_sdk_namespace_encoding_and_timeout(vespa):
    service, send = vespa
    send.return_value = response(200, {"fields": {"updated_at_jira": "now"}})
    assert isinstance(service.client, VespaSync)
    assert service.get("index_checkpoint", "a/b ?") == {"updated_at_jira": "now"}
    request = send.call_args.args[0]
    assert request.method == "GET"
    assert request.url == "http://vespa:8080/document/v1/incident/index_checkpoint/docid/a/b%20%3F"
    assert send.call_args.kwargs["timeout"] == 7


def test_missing_document(vespa):
    service, send = vespa
    send.return_value = response(404, {"id": "id:incident:incident::MISSING"})
    assert service.get("incident", "MISSING") is None


@pytest.mark.parametrize("payload", [{"message": "Unknown document type"}, {}, {"id": "missing", "message": "Unknown document type"}])
def test_missing_schema_is_failure(vespa, payload):
    service, send = vespa
    send.return_value = response(404, payload)
    with pytest.raises(DependencyError):
        service.get("incident", "MISSING")


def test_put_feeds_fields(vespa):
    service, send = vespa
    send.return_value = response(200, {"id": "id:incident:index_checkpoint::stream"})
    service.put("index_checkpoint", "stream", {"updated_at_jira": "now"})
    request = send.call_args.args[0]
    assert request.method == "POST"
    assert request.url == "http://vespa:8080/document/v1/incident/index_checkpoint/docid/stream"
    assert json.loads(request.body) == {"fields": {"updated_at_jira": "now"}}
    assert send.call_args.kwargs["timeout"] == 7


@pytest.mark.parametrize("status,payload", [(200, {}), (404, {"message": "Unknown document type"})])
def test_put_requires_confirmation(vespa, status, payload):
    service, send = vespa
    send.return_value = response(status, payload)
    with pytest.raises(DependencyError):
        service.put("incident", "test", {})


def test_ready_checks_both_schemas(vespa):
    service, send = vespa
    send.return_value = response(200, {"root": {}})
    service.ready()
    assert [json.loads(call.args[0].body) for call in send.call_args_list] == [
        {"yql": f"select * from {schema} where true", "hits": 0}
        for schema in ("incident", "index_checkpoint")
    ]
    assert all(call.kwargs["timeout"] == 7 for call in send.call_args_list)


@pytest.mark.parametrize("payload", [{"root": {"errors": [{"message": "Unknown schema"}]}}, {"errors": ["failure"]}])
def test_ready_rejects_query_errors(vespa, payload):
    service, send = vespa
    send.return_value = response(200, payload)
    with pytest.raises(DependencyError):
        service.ready()


@pytest.mark.parametrize("operation", ["get", "put", "ready"])
def test_http_errors_propagate(vespa, operation):
    service, send = vespa
    send.return_value = response(500, {})
    with pytest.raises(HTTPError):
        if operation == "get":
            service.get("incident", "test")
        elif operation == "put":
            service.put("incident", "test", {})
        else:
            service.ready()


def test_close_releases_session(vespa, monkeypatch):
    service, _ = vespa
    close = Mock()
    monkeypatch.setattr(service.client.http_session, "close", close)
    service.close()
    service.close()
    close.assert_called_once()
