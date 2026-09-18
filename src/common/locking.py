import fcntl
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator

from src.common.errors import IndexAlreadyRunning


@contextmanager
def index_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise IndexAlreadyRunning("Индексация уже выполняется") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
