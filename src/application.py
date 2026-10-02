import logging
from contextlib import asynccontextmanager

from dishka import Container
from fastapi import FastAPI, HTTPException

from src.core.incident_vectorizer import IncidentVectorizer
from src.core.confluence_vectorizer import ConfluenceVectorizer
from src.common.errors import IndexAlreadyRunning
from src.models.request_models import IndexResult
from src.routers.general import GeneralRouter
from src.services.vespa_service import VespaService


class Application:
    def __init__(self, container: Container):
        self.container = container

    def start_app(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            try:
                yield
            finally:
                self.container.close()

        try:
            router = GeneralRouter(self.container.get(IncidentVectorizer), self.container.get(VespaService))
            app = FastAPI(title="Incident Vectorizer", lifespan=lifespan)
            app.include_router(router.router, prefix=router.prefix, tags=router.tags)

            @app.post("/api/v1/index/confluence", tags=router.tags)
            def index_confluence() -> IndexResult:
                try:
                    # Resolve lazily: Jira-only deployments need no Confluence settings.
                    return self.container.get(ConfluenceVectorizer).run()
                except IndexAlreadyRunning:
                    raise HTTPException(409, "Индексация уже выполняется") from None
                except Exception as exc:
                    logging.getLogger(__name__).error("Индексация Confluence прервана (%s)", type(exc).__name__)
                    raise HTTPException(502, "Индексация Confluence прервана") from None

            return app
        except Exception:
            self.container.close()
            raise
