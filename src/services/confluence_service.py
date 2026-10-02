import httpx

from src.common.config import ConfluenceConfig
from src.models.confluence_models import ConfluenceRecordsPage


class ConfluenceService:
    def __init__(self, config: ConfluenceConfig):
        self.config = config
        self.client = httpx.Client(
            base_url=str(config.base_url).rstrip("/"),
            headers={"Accept": "application/json"},
            timeout=config.timeout,
        )

    def get_records(self) -> ConfluenceRecordsPage:
        params: dict[str, str | int] = {
            "content_type": "page", "body_format": "text", "page_size": self.config.page_size,
        }
        if self.config.space_key:
            params["space_key"] = self.config.space_key
        response = self.client.get("/api/v1/confluence/records", params=params)
        response.raise_for_status()
        return ConfluenceRecordsPage.model_validate(response.json())

    def close(self) -> None:
        self.client.close()
