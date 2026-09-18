from src.models.jira_models import JiraComment, JiraIssue
from src.core.transform import build_document


def issue(description: str | None = None) -> JiraIssue:
    return JiraIssue.model_validate(
        {
            "key": "PROJ-1",
            "fields": {
                "description": description,
                "status": {"name": "Open"},
                "updated": "2026-09-17T10:00:00+00:00",
            },
        }
    )


def test_empty_description_and_comments_are_deterministic() -> None:
    first = build_document(issue(), [])
    second = build_document(issue(), [])
    assert first.text == "Описание:\n\nКомментарии:\n"
    assert first.content_hash == second.content_hash


def test_comments_are_sorted_and_newlines_normalized() -> None:
    comments = [
        JiraComment.model_validate(
            {"id": "2", "author": {"displayName": "Боб"}, "body": "второй\r\n", "created": "2026-09-17T11:00:00Z"}
        ),
        JiraComment.model_validate(
            {"id": "1", "author": {"displayName": "Алиса"}, "body": "первый", "created": "2026-09-17T10:00:00Z"}
        ),
    ]
    document = build_document(issue("текст\r\n"), comments)
    assert document.text.index("Алиса") < document.text.index("Боб")
    assert "\r" not in document.text
