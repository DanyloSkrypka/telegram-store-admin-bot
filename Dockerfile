FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY store_bot ./store_bot
COPY assets ./assets

# docker build --target test .   -> runs the test suite inside the image
FROM base AS test
COPY requirements-dev.txt pytest.ini ./
COPY tests ./tests
RUN pip install --no-cache-dir pytest pytest-asyncio && python -m pytest -q

FROM base AS runtime
RUN useradd --create-home bot && mkdir -p /app/data && chown bot /app/data
USER bot
VOLUME ["/app/data"]
# without BOT_TOKEN the container runs the offline demo instead of crashing
CMD ["python", "-m", "store_bot"]
