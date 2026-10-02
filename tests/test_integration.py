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
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0] + [0.0] * 2047}]})
    embedder.client = httpx.Client(base_url="http://embedder/v1/", transport=httpx.MockTransport(embed))
    jira = Mock()
    jira.iter_issue_keys.return_value = ["SMOKE-1"]
    jira.get_comments.return_value = []
    jira.get_issue.return_value = JiraIssue.model_validate({"key": "SMOKE-1", "fields": {"description": "Smoke test", "status": {"name": "Open"}, "updated": "2026-09-18T10:00:00Z"}})
    config = JiraConfig(jira_url="https://smoke.test", jira_token="fake")
    repository = TicketRepository(vespa, embedder)
    vectorizer = IncidentVectorizer(jira, repository, config, RuntimeConfig(lock_file=tmp_path / "index.lock"))
    try:
        first = vectorizer.run()
        assert first.failed == 0
        fields = vespa.get("incident", "SMOKE-1")
        assert fields["text"].startswith("Описание:")
        assert fields["embedding"]
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


@pytest.mark.skipif(not os.getenv("INCIDENT_TEST_VESPA_URL"), reason="Dedicated test Vespa URL not set")
def test_real_confluence_weighted_query(tmp_path):
    import time
    from src.core.confluence_vectorizer import ConfluenceVectorizer
    from src.models.confluence_models import ConfluenceRecordsPage
    from src.repositories.confluence_page_repository import ConfluencePageRepository

    vespa = VespaService(VespaConfig(url=os.environ["INCIDENT_TEST_VESPA_URL"]))
    vector = [1.0] + [0.0] * 2047
    embedder = Mock(version="smoke-2048")
    embedder.embed_texts.return_value = [vector]
    source = Mock()
    source.get_records.return_value = ConfluenceRecordsPage(
        count=1, content_type="page", body_format="text",
        records=[{"id": "CONFLUENCE-SMOKE-1", "body": "Confluence smoke content"}],
    )
    vectorizer = ConfluenceVectorizer(source, ConfluencePageRepository(vespa, embedder), RuntimeConfig(lock_file=tmp_path / "index.lock"))
    try:
        assert vectorizer.run().failed == 0
        assert vespa.get("confluence_page", "CONFLUENCE-SMOKE-1")["text"] == "Confluence smoke content"
        assert vectorizer.run().changed == 0
        query = {
            "yql": 'select * from confluence_page where page_id contains "CONFLUENCE-SMOKE-1" and ({targetHits:10,approximate:false}nearestNeighbor(embedding,q_embedding) or userQuery())',
            "query": "smoke", "ranking": "weighted", "hits": 1,
            "input.query(q_embedding)": vector,
        }
        for _ in range(20):
            response = vespa.client.query(body=query)
            assert response.is_successful()
            assert not response.json.get("root", {}).get("errors")
            hits = response.json.get("root", {}).get("children", [])
            if hits:
                assert hits[0]["fields"]["page_id"] == "CONFLUENCE-SMOKE-1"
                assert hits[0]["relevance"] > 0
                break
            time.sleep(0.5)
        else:
            pytest.fail("Confluence document did not become searchable")
    finally:
        vespa.close()
