FROM python:3.12-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY function ./function
RUN uv sync --frozen --no-dev --no-editable


FROM python:3.12-slim

COPY --from=build /app/.venv /app/.venv

EXPOSE 9443
ENTRYPOINT ["/app/.venv/bin/aws-vpn-function"]
