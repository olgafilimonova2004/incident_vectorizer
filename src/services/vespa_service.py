from typing import Any
from urllib.parse import quote

import httpx

from src.common.config import VespaConfig
from src.common.errors import DependencyError


class VespaService:
    def __init__(self, config: VespaConfig):
        self.client = httpx.Client(base_url=str(config.url).rstrip("/"), timeout=config.timeout)

    def _path(self, schema: str, doc_id: str) -> str:
        return f"/document/v1/incident/{schema}/docid/{quote(doc_id, safe='')}"

    def get(self, schema: str, doc_id: str) -> dict[str, Any] | None:
        response = self.client.get(self._path(schema, doc_id))
        if response.status_code == 404:
            # An undeployed document type must not be treated as an absent document.
            payload = response.json()
            if "id" in payload and "message" not in payload:
                return None
        response.raise_for_status()
        return response.json()["fields"]

    def put(self, schema: str, doc_id: str, fields: dict[str, Any]) -> None:
        response = self.client.post(self._path(schema, doc_id), json={"fields": fields})
        response.raise_for_status()
        if "id" not in response.json():
            raise DependencyError("Vespa не подтвердила запись документа")

    def ready(self) -> None:
        for schema in ("incident", "index_checkpoint"):
            response = self.client.post("/search/", json={"yql": f"select * from {schema} where true", "hits": 0})
            response.raise_for_status()
            if response.json().get("root", {}).get("errors") or response.json().get("errors"):
                raise DependencyError("Схемы Vespa не готовы")

    def close(self) -> None:
        self.client.close()
