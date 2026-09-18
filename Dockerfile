FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY scripts/ ./scripts/

ENV PORT=8000 \
    GROQ_MODEL=openai/gpt-oss-120b \
    GROQ_FALLBACK_MODEL=openai/gpt-oss-20b \
    GROQ_BASE_URL=https://api.groq.com/openai/v1

EXPOSE 8000

# GROQ_API_KEY must be provided at runtime via -e GROQ_API_KEY=... (never baked in)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
