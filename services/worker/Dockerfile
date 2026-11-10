FROM python:3.11-slim
WORKDIR /app
ENV PYTHONPATH=/app/services/worker:/app/services:/app \
    HF_HOME=/opt/hf PYTHONUNBUFFERED=1
# CPU-only torch keeps the image small
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY services/worker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
# bake the embedding model into the image so the stack starts without internet access
ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"
COPY services /app/services
COPY pipeline /app/pipeline
COPY prompts /app/prompts
COPY corpus /app/corpus
COPY contracts /app/contracts
COPY eval /app/eval
COPY load /app/load
COPY tests /app/tests
CMD ["python", "-m", "worker.main"]
