from datetime import datetime, timezone

from src.models.jira_models import TicketDocument
from src.clients.lm_client import LMClient
from src.services.vespa_service import VespaService


class TicketRepository:
    def __init__(self, vespa: VespaService, embedder: LMClient):
        self.vespa = vespa
        self.embedder = embedder

    def upsert(self, document: TicketDocument, *, force: bool = False) -> bool:
        old = None if force else self.vespa.get("incident", document.ticket_id)
        fields = document.model_dump(mode="json")
        fields["updated_at_jira"] = document.updated_at_jira.isoformat() if document.updated_at_jira else ""
        same_vector = bool(old and old.get("content_hash") == document.content_hash and old.get("embedding_model_version") == self.embedder.version and old.get("embedding"))
        if same_vector and old and all(old.get(key) == value for key, value in fields.items()):
            return False
        fields["embedding"] = old["embedding"] if same_vector and old else {"values": self.embedder.embed_texts([document.text])[0]}
        fields["embedding_model_version"] = self.embedder.version
        fields["updated_at_db"] = datetime.now(timezone.utc).isoformat()
        self.vespa.put("incident", document.ticket_id, fields)
        return True
