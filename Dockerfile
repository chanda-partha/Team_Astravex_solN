FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY static/ ./static/
COPY frontend/ ./frontend/
COPY samples/ ./samples/
COPY scripts/ ./scripts/

ENV PORT=8000 \
    GROQ_MODEL=llama-3.1-8b-instant \
    GROQ_FALLBACK_MODEL=llama-3.3-70b-versatile \
    GROQ_BASE_URL=https://api.groq.com/openai/v1

EXPOSE 8000

# GROQ_API_KEY / OPENAI_API_KEY must be provided at runtime via environment variable
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
