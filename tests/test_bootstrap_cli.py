from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from main import create_app
from src import cli
from src.models.request_models import IndexResult


def test_bootstrap_and_shutdown(monkeypatch):
    monkeypatch.setenv("JIRA_INDEXER_JIRA_URL", "https://jira.test")
    monkeypatch.setenv("JIRA_INDEXER_BASE_URL", "http://manager")
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/ping").json() == "pong"
        assert "/api/v1/index" in client.get("/openapi.json").json()["paths"]


@pytest.mark.parametrize("failed,code", [(0, 0), (1, 1)])
def test_cli_result_and_close(monkeypatch, capsys, failed, code):
    container = Mock()
    container.get.return_value.run.return_value = IndexResult(processed=1, failed=failed)
    monkeypatch.setattr(cli, "initialize_container", lambda: container)
    monkeypatch.setattr("sys.argv", ["jira-index"])
    with pytest.raises(SystemExit) as exc:
        cli.index_main()
    assert exc.value.code == code
    container.get.return_value.run.assert_called_once_with()
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


def test_jira_full_option_removed(monkeypatch):
    monkeypatch.setattr("sys.argv", ["jira-index", "--full"])
    with pytest.raises(SystemExit) as exc:
        cli.index_main()
    assert exc.value.code == 2


@pytest.mark.parametrize("entrypoint", [cli.jira_index_force_main, cli.confluence_index_force_main])
@pytest.mark.parametrize("failed,error,code", [(0, False, 0), (1, False, 1), (0, True, 1)])
def test_force_commands(monkeypatch, capsys, entrypoint, failed, error, code):
    container = Mock()
    container.get.return_value.run.return_value = IndexResult(processed=1, changed=1-failed, failed=failed)
    if error:
        container.get.return_value.run.side_effect = RuntimeError("private")
    monkeypatch.setattr(cli, "initialize_container", lambda: container)
    monkeypatch.setattr("sys.argv", ["index-force"])
    with pytest.raises(SystemExit) as exc:
        entrypoint()
    assert exc.value.code == code
    container.get.return_value.run.assert_called_once_with(force=True)
    container.close.assert_called_once()
    if not error:
        assert '"processed":1' in capsys.readouterr().out


@pytest.mark.parametrize("mode", ["found", "missing", "error"])
def test_jira_dump_uses_manager(monkeypatch, capsys, mode):
    import json
    from src.models.jira_models import JiraTasksPage
    from unittest.mock import MagicMock

    record = {"key": "PROJ-1", "description": "*raw*", "comments": []}
    service = MagicMock()
    service.__enter__.return_value = service
    service.get_tasks.return_value = JiraTasksPage(
        count=1 if mode == "found" else 0, jql='key = "PROJ-1"',
        tasks=[record] if mode == "found" else [],
    )
    if mode == "error":
        service.get_tasks.side_effect = RuntimeError("private")
    monkeypatch.setenv("JIRA_INDEXER_BASE_URL", "http://manager")
    monkeypatch.setenv("JIRA_INDEXER_JIRA_URL", "http://jira")
    monkeypatch.setattr(cli, "JiraClient", lambda config: service)
    monkeypatch.setattr("sys.argv", ["jira-dump", "PROJ-1"])
    if mode == "found":
        cli.dump_issue_main()
        assert json.loads(capsys.readouterr().out) == record
    else:
        with pytest.raises(SystemExit) as exc:
            cli.dump_issue_main()
        assert exc.value.code == 1
        assert "private" not in capsys.readouterr().err
    service.get_tasks.assert_called_once_with('key = "PROJ-1"', 100)
    service.__exit__.assert_called_once()
