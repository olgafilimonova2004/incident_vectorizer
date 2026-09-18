FROM python:3.11-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.4 /uv /bin/uv
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY main.py ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.11-slim
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1
WORKDIR /app
USER nobody
EXPOSE 8001
CMD ["incident-vectorizer"]
