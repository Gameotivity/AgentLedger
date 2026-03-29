FROM python:3.12-slim

WORKDIR /app

COPY agentledger-server/pyproject.toml .
RUN pip install --no-cache-dir .

COPY agentledger-server/app ./app
COPY pricing ./pricing

EXPOSE 8100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
