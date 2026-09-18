import argparse
import json
import logging

from src.common.config import JiraConfig
from src.common.container import initialize_container
from src.core.incident_vectorizer import IncidentVectorizer
from src.services.jira_service import JiraService


def dump_issue_main() -> None:
    parser = argparse.ArgumentParser(description="Исходные ответы Jira для одного тикета")
    parser.add_argument("key")
    args = parser.parse_args()
    settings = JiraConfig()  # type: ignore[call-arg]
    with JiraService(str(settings.jira_url), settings.jira_token.get_secret_value()) as jira:
        print(json.dumps(jira.get_issue_raw(args.key), ensure_ascii=False, indent=2))
        for page in jira.iter_comment_pages_raw(args.key, settings.page_size):
            print(json.dumps(page, ensure_ascii=False, indent=2))


def index_main() -> None:
    parser = argparse.ArgumentParser(description="Индексация Jira в Vespa")
    parser.add_argument("--full", action="store_true", help="Обойти весь JQL без границы checkpoint")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    container = initialize_container()
    try:
        result = container.get(IncidentVectorizer).run(full=args.full)
        print(result.model_dump_json())
        code = 1 if result.failed else 0
    except Exception as exc:
        logging.error("Индексация прервана (%s)", type(exc).__name__)
        code = 1
    finally:
        container.close()
    raise SystemExit(code)
