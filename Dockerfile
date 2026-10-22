# syntax=docker/dockerfile:1
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Dependencies first, so a code change doesn't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# The bot reads scenarios/ and the grilling skill at runtime (spec 5.5).
COPY zvonilka ./zvonilka
COPY scenarios ./scenarios
COPY .agents/skills/grilling ./.agents/skills/grilling
RUN uv sync --frozen --no-dev

RUN useradd --uid 10001 --no-create-home --home-dir /app zvonilka \
    && mkdir -p /app/data \
    && chown zvonilka /app/data
USER zvonilka

# SQLite: memory, sessions, scheduled calls. Mount a volume here.
VOLUME ["/app/data"]

CMD ["python", "-m", "zvonilka"]
