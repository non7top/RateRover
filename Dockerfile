FROM python:3.13-slim

RUN useradd -m app -d /app -u 65533 -s /bin/false
RUN mkdir -p /app && chown -R app: /app

USER app

WORKDIR /app


ENV TELEGRAM_TOKEN=${TELEGRAM_TOKEN}

ENV VIRTUAL_ENV=/app/venv
RUN python -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY --chown=app:app bot.py requirements.txt main.py .
RUN --mount=type=cache,target=/app/.cache/pip pip install --no-cache-dir -r /app/requirements.txt && rm -f /app/requirements.txt
RUN cd /app/ && python -m compileall .
