from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ConfluenceRecord(BaseModel):
    id: str = Field(min_length=1)
    body: str | None = None
    updated_at: datetime | None = None


class ConfluenceRecordsPage(BaseModel):
    count: int
    space_key: str | None = None
    content_type: str
    body_format: str
    # Validate each record during indexing so one bad record does not stop others.
    records: list[dict[str, Any]] = Field(default_factory=list)


class ConfluenceDocument(BaseModel):
    page_id: str
    text: str
    content_hash: str
    updated_at_confluence: str
