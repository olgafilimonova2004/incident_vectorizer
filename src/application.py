from contextlib import asynccontextmanager

from dishka import Container
from fastapi import FastAPI

from src.core.incident_vectorizer import IncidentVectorizer
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
            return app
        except Exception:
            self.container.close()
            raise
