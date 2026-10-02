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


def index_main(*, force: bool = False) -> None:
    parser = argparse.ArgumentParser(description="Принудительная переиндексация Jira в Vespa" if force else "Индексация Jira в Vespa")
    parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    container = initialize_container()
    try:
        vectorizer = container.get(IncidentVectorizer)
        result = vectorizer.run(force=True) if force else vectorizer.run()
        print(result.model_dump_json())
        code = 1 if result.failed else 0
    except Exception as exc:
        logging.error("Индексация прервана (%s)", type(exc).__name__)
        code = 1
    finally:
        container.close()
    raise SystemExit(code)


def confluence_index_main(*, force: bool = False) -> None:
    from src.core.confluence_vectorizer import ConfluenceVectorizer

    parser = argparse.ArgumentParser(description="Принудительная переиндексация Confluence в Vespa" if force else "Индексация Confluence в Vespa")
    parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    container = initialize_container()
    try:
        vectorizer = container.get(ConfluenceVectorizer)
        result = vectorizer.run(force=True) if force else vectorizer.run()
        print(result.model_dump_json())
        code = 1 if result.failed else 0
    except Exception as exc:
        logging.error("Индексация Confluence прервана (%s)", type(exc).__name__)
        code = 1
    finally:
        container.close()
    raise SystemExit(code)


def confluence_dump_main() -> None:
    from src.common.config import ConfluenceConfig
    from src.services.confluence_service import ConfluenceService

    parser = argparse.ArgumentParser(description="JSON страницы Confluence с body в формате text")
    parser.add_argument("page_id")
    args = parser.parse_args()
    service = ConfluenceService(ConfluenceConfig())  # type: ignore[call-arg]
    try:
        page = service.get_records()
        record = next((record for record in page.records if record.get("id") == args.page_id), None)
        if record is None:
            parser.exit(1, "Страница не найдена в выбранных пространствах Confluence\n")
        print(json.dumps(record, ensure_ascii=False, indent=2))
    except Exception as exc:
        parser.exit(1, f"Не удалось получить страницу Confluence ({type(exc).__name__})\n")
    finally:
        service.close()


def jira_index_force_main() -> None:
    index_main(force=True)


def confluence_index_force_main() -> None:
    confluence_index_main(force=True)
