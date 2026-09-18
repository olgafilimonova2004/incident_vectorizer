from src.application import Application
from src.common.container import initialize_container


def setup() -> Application:
    return Application(initialize_container())
