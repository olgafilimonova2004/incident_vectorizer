import logging

import uvicorn

from src.bootstrap import setup


def create_app():
    return setup().start_app()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run("main:create_app", factory=True, host="0.0.0.0", port=8001, workers=1)


if __name__ == "__main__":
    main()
