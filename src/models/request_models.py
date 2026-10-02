from pydantic import BaseModel


class IndexResult(BaseModel):
    processed: int = 0
    changed: int = 0
    failed: int = 0
