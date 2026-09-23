from contextlib import ExitStack
from typing import Any

from requests import Session
from vespa.application import Vespa

from src.common.config import VespaConfig
from src.common.errors import DependencyError


class _TimeoutSession(Session):
    def __init__(self, timeout: float):
        super().__init__()
        self.timeout = timeout

    def request(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("timeout", self.timeout)
        return super().request(*args, **kwargs)


class VespaService:
    def __init__(self, config: VespaConfig):
        app = Vespa(url=str(config.url).rstrip("/"))
        with ExitStack() as resources:
            # Pyvespa forwards method kwargs as Vespa query parameters, so set
            # the network timeout on its underlying session instead.
            session = resources.enter_context(_TimeoutSession(config.timeout))
            self.client = resources.enter_context(app.syncio(session=session))
            self._resources = resources.pop_all()

    def get(self, schema: str, doc_id: str) -> dict[str, Any] | None:
        response = self.client.get_data(schema=schema, data_id=doc_id, namespace="incident")
        if response.status_code == 404:
            # An undeployed document type must not be treated as an absent document.
            payload = response.json
            if "id" in payload and "message" not in payload:
                return None
        if not response.is_successful():
            raise DependencyError("Vespa не смогла получить документ")
        return response.json["fields"]

    def put(self, schema: str, doc_id: str, fields: dict[str, Any]) -> None:
        response = self.client.feed_data_point(schema=schema, data_id=doc_id, fields=fields, namespace="incident")
        if not response.is_successful() or "id" not in response.json:
            raise DependencyError("Vespa не подтвердила запись документа")

    def ready(self) -> None:
        for schema in ("incident", "index_checkpoint"):
            response = self.client.query(body={"yql": f"select * from {schema} where true", "hits": 0})
            if not response.is_successful() or response.json.get("root", {}).get("errors") or response.json.get("errors"):
                raise DependencyError("Схемы Vespa не готовы")

    def close(self) -> None:
        self._resources.close()
