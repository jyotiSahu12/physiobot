# Portable image (works on Railway / Fly / any container host). Render uses
# render.yaml instead, but this keeps you host-independent.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV LLM_PROVIDER=groq
EXPOSE 8000

CMD ["sh", "-c", "uvicorn physiobot.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
