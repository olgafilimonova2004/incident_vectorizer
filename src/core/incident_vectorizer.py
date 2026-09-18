import hashlib
import json
import logging
from datetime import timedelta

from src.common.config import JiraConfig, RuntimeConfig
from src.common.locking import index_lock
from src.core.transform import build_document
from src.models.request_models import IndexResult
from src.repositories.ticket_repository import TicketRepository
from src.services.jira_service import JiraService, jql_with_updated_since

logger = logging.getLogger(__name__)


class IncidentVectorizer:
    def __init__(self, jira: JiraService, repository: TicketRepository, config: JiraConfig, runtime: RuntimeConfig):
        self.jira, self.repository, self.config, self.runtime = jira, repository, config, runtime
        self.stream_id = hashlib.sha256(json.dumps([str(config.jira_url).rstrip("/"), config.jql]).encode()).hexdigest()

    def run(self, full: bool = False) -> IndexResult:
        with index_lock(self.runtime.lock_file):
            self.repository.vespa.ready()
            previous = self.repository.checkpoint(self.stream_id)
            since = previous - timedelta(seconds=self.config.overlap_seconds) if previous and not full else None
            jql = jql_with_updated_since(self.config.jql, since)
            latest = previous
            result = IndexResult()
            for key in self.jira.iter_issue_keys(jql, self.config.page_size):
                result.processed += 1
                try:
                    issue = self.jira.get_issue(key)
                    comments = self.jira.get_comments(key, self.config.page_size)
                    document = build_document(issue, comments)
                    result.changed += int(self.repository.upsert(document))
                    latest = max(latest, document.updated_at_jira) if latest else document.updated_at_jira
                except Exception as exc:
                    # Do not log upstream response bodies, credentials or ticket contents.
                    logger.error("Не удалось обработать тикет %s (%s)", key, type(exc).__name__)
                    result.failed += 1
            if result.failed == 0 and latest is not None and (previous is None or latest > previous):
                self.repository.save_checkpoint(self.stream_id, latest)
                result.checkpoint_advanced = True
            return result
