from datetime import datetime, timezone

from src.models.jira_models import TicketDocument
from src.services.embedder_service import EmbedderService
from src.services.vespa_service import VespaService


class TicketRepository:
    def __init__(self, vespa: VespaService, embedder: EmbedderService):
        self.vespa = vespa
        self.embedder = embedder

    def upsert(self, document: TicketDocument) -> bool:
        old = self.vespa.get("incident", document.ticket_id)
        fields = document.model_dump(mode="json")
        fields["updated_at_jira"] = document.updated_at_jira.isoformat()
        same_vector = bool(old and old.get("content_hash") == document.content_hash and old.get("embedding_model_version") == self.embedder.version and old.get("embedding"))
        if same_vector and old and all(old.get(key) == value for key, value in fields.items()):
            return False
        fields["embedding"] = old["embedding"] if same_vector and old else {"values": self.embedder.embed_texts([document.text])[0]}
        fields["embedding_model_version"] = self.embedder.version
        fields["updated_at_db"] = datetime.now(timezone.utc).isoformat()
        self.vespa.put("incident", document.ticket_id, fields)
        return True

    def checkpoint(self, stream_id: str) -> datetime | None:
        state = self.vespa.get("index_checkpoint", stream_id)
        return datetime.fromisoformat(state["updated_at_jira"]) if state else None

    def save_checkpoint(self, stream_id: str, updated: datetime) -> None:
        self.vespa.put("index_checkpoint", stream_id, {"updated_at_jira": updated.isoformat()})
