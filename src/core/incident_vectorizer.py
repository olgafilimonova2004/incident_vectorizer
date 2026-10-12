import logging

from src.clients.jira_client import JiraClient
from src.common.config import JiraConfig, RuntimeConfig
from src.common.locking import index_lock
from src.core.transform import build_document
from src.models.jira_models import JiraIssue
from src.models.request_models import IndexResult
from src.repositories.ticket_repository import TicketRepository

logger = logging.getLogger(__name__)


class IncidentVectorizer:
    def __init__(self, jira: JiraClient, repository: TicketRepository, config: JiraConfig, runtime: RuntimeConfig):
        self.jira, self.repository, self.config, self.runtime = jira, repository, config, runtime

    def run(self, *, force: bool = False) -> IndexResult:
        with index_lock(self.runtime.lock_file):
            self.repository.vespa.ready()
            result = IndexResult()
            page = self.jira.get_tasks(self.config.jql, self.config.page_size)
            for raw in page.tasks:
                result.processed += 1
                try:
                    issue = JiraIssue.model_validate(raw)
                    url = f"{str(self.config.jira_url).rstrip('/')}/browse/{issue.key}"
                    document = build_document(issue, url=url)
                    result.changed += int(self.repository.upsert(document, force=force))
                except Exception as exc:
                    # Do not log upstream response bodies, credentials or ticket contents.
                    logger.error("Не удалось обработать тикет %s (%s)", raw.get("key", "<unknown>"), type(exc).__name__)
                    result.failed += 1
            return result
