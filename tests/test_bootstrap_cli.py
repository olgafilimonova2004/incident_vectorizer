from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from main import create_app
from src import cli
from src.models.request_models import IndexResult


def test_bootstrap_and_shutdown(monkeypatch):
    monkeypatch.setenv("JIRA_INDEXER_JIRA_URL", "https://jira.test")
    monkeypatch.setenv("JIRA_INDEXER_JIRA_TOKEN", "secret")
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/ping").json() == "pong"
        assert "/api/v1/index" in client.get("/openapi.json").json()["paths"]


@pytest.mark.parametrize("failed,code", [(0, 0), (1, 1)])
def test_cli_result_and_close(monkeypatch, capsys, failed, code):
    container = Mock()
    container.get.return_value.run.return_value = IndexResult(processed=1, failed=failed)
    monkeypatch.setattr(cli, "initialize_container", lambda: container)
    monkeypatch.setattr("sys.argv", ["jira-index", "--full"])
    with pytest.raises(SystemExit) as exc:
        cli.index_main()
    assert exc.value.code == code
    container.get.return_value.run.assert_called_once_with(full=True)
    container.close.assert_called_once()
    assert '"processed":1' in capsys.readouterr().out


def test_cli_error_is_nonzero_and_closes(monkeypatch):
    container = Mock()
    container.get.return_value.run.side_effect = RuntimeError("secret response")
    monkeypatch.setattr(cli, "initialize_container", lambda: container)
    monkeypatch.setattr("sys.argv", ["jira-index"])
    with pytest.raises(SystemExit) as exc:
        cli.index_main()
    assert exc.value.code == 1
    container.close.assert_called_once()
