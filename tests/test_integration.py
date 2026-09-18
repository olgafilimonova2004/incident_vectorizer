"""Opt-in test: uses a dedicated Vespa instance, mock Jira and HTTP embedder."""
import os
from unittest.mock import Mock

import httpx
import pytest

from src.common.config import EmbedderConfig, JiraConfig, RuntimeConfig, VespaConfig
from src.core.incident_vectorizer import IncidentVectorizer
from src.models.jira_models import JiraIssue
from src.repositories.ticket_repository import TicketRepository
from src.services.embedder_service import EmbedderService
from src.services.vespa_service import VespaService


@pytest.mark.skipif(not os.getenv("INCIDENT_TEST_VESPA_URL"), reason="Dedicated test Vespa URL not set")
def test_real_vespa_pipeline(tmp_path):
    vespa = VespaService(VespaConfig(url=os.environ["INCIDENT_TEST_VESPA_URL"]))
    embedder = EmbedderService(EmbedderConfig())
    embedder.client.close()
    calls = []
    def embed(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0] + [0.0] * 2559}]})
    embedder.client = httpx.Client(base_url="http://embedder/v1/", transport=httpx.MockTransport(embed))
    jira = Mock()
    jira.iter_issue_keys.return_value = ["SMOKE-1"]
    jira.get_comments.return_value = []
    jira.get_issue.return_value = JiraIssue.model_validate({"key": "SMOKE-1", "fields": {"description": "Smoke test", "status": {"name": "Open"}, "updated": "2026-09-18T10:00:00Z"}})
    config = JiraConfig(jira_url="https://smoke.test", jira_token="fake")
    repository = TicketRepository(vespa, embedder)
    vectorizer = IncidentVectorizer(jira, repository, config, RuntimeConfig(lock_file=tmp_path / "index.lock"))
    try:
        first = vectorizer.run(full=True)
        assert first.failed == 0
        fields = vespa.get("incident", "SMOKE-1")
        assert fields["text"].startswith("Описание:")
        assert fields["embedding"]
        assert repository.checkpoint(vectorizer.stream_id) is not None
        call_count = len(calls)
        assert vectorizer.run().changed == 0
        assert len(calls) == call_count
        jira.get_issue.return_value.fields.status.name = "Closed"
        assert vectorizer.run().changed == 1
        assert len(calls) == call_count
        assert vespa.get("incident", "SMOKE-1")["status"] == "Closed"
    finally:
        vespa.close()
        embedder.close()
