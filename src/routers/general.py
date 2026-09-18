import logging

from fastapi import APIRouter, HTTPException

from src.common.errors import IndexAlreadyRunning
from src.core.incident_vectorizer import IncidentVectorizer
from src.interfaces.router import BaseRouter
from src.models.request_models import IndexRequest, IndexResult
from src.services.vespa_service import VespaService

logger = logging.getLogger(__name__)


class GeneralRouter(BaseRouter):
    def __init__(self, vectorizer: IncidentVectorizer, vespa: VespaService):
        self.vectorizer, self.vespa = vectorizer, vespa

    @property
    def router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/ping")
        def ping() -> str:
            return "pong"

        @router.get("/ready")
        def ready() -> dict[str, str]:
            try:
                self.vespa.ready()
            except Exception:
                raise HTTPException(503, "Vespa не готова") from None
            return {"status": "ok"}

        @router.post("/index")
        def index(request: IndexRequest) -> IndexResult:
            try:
                return self.vectorizer.run(full=request.full)
            except IndexAlreadyRunning:
                raise HTTPException(409, "Индексация уже выполняется") from None
            except Exception as exc:
                logger.error("Индексация прервана (%s)", type(exc).__name__)
                raise HTTPException(502, "Индексация прервана; checkpoint не продвинут") from None

        return router
