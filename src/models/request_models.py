from pydantic import BaseModel


class IndexRequest(BaseModel):
    full: bool = False


class IndexResult(BaseModel):
    processed: int = 0
    changed: int = 0
    failed: int = 0
    checkpoint_advanced: bool = False
