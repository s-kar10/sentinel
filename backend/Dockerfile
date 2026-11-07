FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system sentinel && adduser --system --ingroup sentinel sentinel \
    && mkdir -p /run/sentinel-secrets \
    && chown sentinel:sentinel /run/sentinel-secrets \
    && chmod 700 /run/sentinel-secrets

COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations

USER sentinel
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
