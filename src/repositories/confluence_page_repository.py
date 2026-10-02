from datetime import datetime, timezone

from src.models.confluence_models import ConfluenceDocument
from src.services.embedder_service import EmbedderService
from src.services.vespa_service import VespaService


class ConfluencePageRepository:
    def __init__(self, vespa: VespaService, embedder: EmbedderService):
        self.vespa = vespa
        self.embedder = embedder

    def upsert(self, document: ConfluenceDocument, *, force: bool = False) -> bool:
        old = None if force else self.vespa.get("confluence_page", document.page_id)
        fields = document.model_dump(mode="json")
        same_vector = bool(old and old.get("content_hash") == document.content_hash and old.get("embedding_model_version") == self.embedder.version and old.get("embedding"))
        if same_vector and old and all(old.get(key) == value for key, value in fields.items()):
            return False
        fields["embedding"] = old["embedding"] if same_vector and old else {"values": self.embedder.embed_texts([document.text])[0]}
        fields["embedding_model_version"] = self.embedder.version
        fields["updated_at_db"] = datetime.now(timezone.utc).isoformat()
        self.vespa.put("confluence_page", document.page_id, fields)
        return True
