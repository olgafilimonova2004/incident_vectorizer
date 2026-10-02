import logging

from src.common.config import JiraConfig, RuntimeConfig
from src.common.locking import index_lock
from src.core.transform import build_document
from src.models.request_models import IndexResult
from src.repositories.ticket_repository import TicketRepository
from src.services.jira_service import JiraService

logger = logging.getLogger(__name__)


class IncidentVectorizer:
    def __init__(self, jira: JiraService, repository: TicketRepository, config: JiraConfig, runtime: RuntimeConfig):
        self.jira, self.repository, self.config, self.runtime = jira, repository, config, runtime

    def run(self, *, force: bool = False) -> IndexResult:
        with index_lock(self.runtime.lock_file):
            self.repository.vespa.ready()
            result = IndexResult()
            for key in self.jira.iter_issue_keys(self.config.jql, self.config.page_size):
                result.processed += 1
                try:
                    issue = self.jira.get_issue(key)
                    comments = self.jira.get_comments(key, self.config.page_size)
                    document = build_document(issue, comments)
                    result.changed += int(self.repository.upsert(document, force=force))
                except Exception as exc:
                    # Do not log upstream response bodies, credentials or ticket contents.
                    logger.error("Не удалось обработать тикет %s (%s)", key, type(exc).__name__)
                    result.failed += 1
            return result
