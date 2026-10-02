import hashlib
import logging

from src.common.config import RuntimeConfig
from src.common.locking import index_lock
from src.models.confluence_models import ConfluenceDocument, ConfluenceRecord
from src.models.request_models import IndexResult
from src.repositories.confluence_page_repository import ConfluencePageRepository
from src.services.confluence_service import ConfluenceService

logger = logging.getLogger(__name__)


class ConfluenceVectorizer:
    def __init__(self, confluence: ConfluenceService, repository: ConfluencePageRepository, runtime: RuntimeConfig):
        self.confluence, self.repository, self.runtime = confluence, repository, runtime

    def run(self, *, force: bool = False) -> IndexResult:
        with index_lock(self.runtime.lock_file):
            self.repository.vespa.ready()
            page = self.confluence.get_records()
            result = IndexResult()
            for raw in page.records:
                result.processed += 1
                try:
                    record = ConfluenceRecord.model_validate(raw)
                    if record.body is None or not record.body.strip():
                        raise ValueError("Empty Confluence body")
                    document = ConfluenceDocument(
                        page_id=record.id,
                        text=record.body,
                        content_hash=hashlib.sha256(record.body.encode("utf-8")).hexdigest(),
                        updated_at_confluence=record.updated_at.isoformat() if record.updated_at else "",
                    )
                    result.changed += int(self.repository.upsert(document, force=force))
                except Exception as exc:
                    logger.error("Не удалось обработать запись Confluence #%s (%s)", result.processed, type(exc).__name__)
                    result.failed += 1
            return result
