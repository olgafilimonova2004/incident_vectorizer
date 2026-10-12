from src.models.jira_models import JiraComment, JiraIssue
from src.core.transform import build_document


def issue(description: str | None = None) -> JiraIssue:
    return JiraIssue.model_validate(
        {
            "key": "PROJ-1",
            "description": description,
            "status": "Open",
            "updated_at": "2026-09-17T10:00:00+00:00",
            "comments": [],
        }
    )


def test_empty_description_and_comments_are_deterministic() -> None:
    first = build_document(issue())
    second = build_document(issue())
    assert first.text == "Описание:\n\nКомментарии:\n"
    assert first.content_hash == second.content_hash


def test_comments_are_sorted_and_newlines_normalized() -> None:
    comments = [
        JiraComment.model_validate(
            {"id": "2", "author": "Боб", "body": "второй\r\n", "created": "2026-09-17T11:00:00Z"}
        ),
        JiraComment.model_validate(
            {"id": "1", "author": "Алиса", "body": "первый", "created": "2026-09-17T10:00:00Z"}
        ),
    ]
    task = issue("текст\r\n")
    task.comments = comments
    document = build_document(task)
    assert document.text.index("Алиса") < document.text.index("Боб")
    assert "\r" not in document.text


def test_jira_markup_preserves_readable_content():
    from src.core.transform import normalize_text
    text = 'h2. Заголовок\n* *жирный* и _курсив_\n[сайт|https://example.org]\n||Имя||Значение||\n|a|b|\n{code:python}\nx = a_b * 2\n{code}\n!image.png|width=100!'
    assert normalize_text(text) == 'Заголовок\n• жирный и курсив\nсайт (https://example.org)\nИмя Значение\na b\nx = a_b * 2'
    assert normalize_text('a_b x*y {noformat}*literal*{noformat}') == 'a_b x*y *literal*'
