from collections.abc import Iterator

from dishka import Provider, Scope, make_container, provide

from src.common.config import EmbedderConfig, JiraConfig, RuntimeConfig, VespaConfig
from src.core.incident_vectorizer import IncidentVectorizer
from src.repositories.ticket_repository import TicketRepository
from src.services.embedder_service import EmbedderService
from src.services.jira_service import JiraService
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
    def jira(self, config: JiraConfig) -> Iterator[JiraService]:
        with JiraService(str(config.jira_url), config.jira_token.get_secret_value()) as service:
            yield service

    @provide
    def vespa(self) -> Iterator[VespaService]:
        service = VespaService(VespaConfig())
        try:
            yield service
        finally:
            service.close()

    @provide
    def embedder(self) -> Iterator[EmbedderService]:
        service = EmbedderService(EmbedderConfig())
        try:
            yield service
        finally:
            service.close()

    repository = provide(TicketRepository)
    vectorizer = provide(IncidentVectorizer)


def initialize_container():
    return make_container(AppProvider())
