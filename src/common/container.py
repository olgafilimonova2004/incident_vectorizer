from collections.abc import Iterator

from dishka import Provider, Scope, make_container, provide

from src.clients.confluence_client import ConfluenceClient
from src.clients.jira_client import JiraClient
from src.clients.lm_client import LMClient
from src.common.config import ConfluenceConfig, EmbedderConfig, JiraConfig, RuntimeConfig, VespaConfig
from src.core.confluence_vectorizer import ConfluenceVectorizer
from src.core.incident_vectorizer import IncidentVectorizer
from src.repositories.confluence_page_repository import ConfluencePageRepository
from src.repositories.ticket_repository import TicketRepository
from src.services.vespa_service import VespaService


class AppProvider(Provider):
    scope = Scope.APP

    @provide
    def jira_config(self) -> JiraConfig:
        return JiraConfig()  # type: ignore[call-arg]

    @provide
    def runtime_config(self) -> RuntimeConfig:
        return RuntimeConfig()

    @provide
    def jira(self, config: JiraConfig) -> Iterator[JiraClient]:
        with JiraClient(config) as service:
            yield service

    @provide
    def vespa(self) -> Iterator[VespaService]:
        service = VespaService(VespaConfig())
        try:
            yield service
        finally:
            service.close()

    @provide
    def embedder(self) -> Iterator[LMClient]:
        service = LMClient(EmbedderConfig())
        try:
            yield service
        finally:
            service.close()

    @provide
    def confluence(self) -> Iterator[ConfluenceClient]:
        service = ConfluenceClient(ConfluenceConfig())  # type: ignore[call-arg]
        try:
            yield service
        finally:
            service.close()

    confluence_repository = provide(ConfluencePageRepository)
    confluence_vectorizer = provide(ConfluenceVectorizer)
    repository = provide(TicketRepository)
    vectorizer = provide(IncidentVectorizer)


def initialize_container():
    return make_container(AppProvider())
