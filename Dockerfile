FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

ENV TRIAL_SCOUT_STATE_PATH=/app/data/trials_state.json

EXPOSE 8080

CMD ["trial-scout", "serve", "--host", "0.0.0.0", "--port", "8080"]
