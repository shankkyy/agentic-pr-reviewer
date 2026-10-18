FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# Fixtures are used by tests only; they are not needed in the runtime image.

RUN useradd --create-home --uid 10001 reviewer && mkdir -p /app/data && chown -R reviewer /app/data
USER reviewer

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
