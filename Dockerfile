# Single-container demo: five database services, gateway and dashboard as separate processes talking over HTTP.
# Used for the hosted demo (Hugging Face Spaces, Docker SDK). The two-laptop setup does not need this file.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    VEHICLETRUST_DEMO=1 \
    VEHICLETRUST_KEEP_ENV=1 \
    LLM_UNDERSTANDING=off \
    STREAMLIT_PORT=7860 \
    STREAMLIT_SERVER_ENABLE_CORS=false \
    STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=false

RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 && rm -rf /var/lib/apt/lists/*

# Hugging Face runs containers as uid 1000; the app writes its SQLite files into its own folder.
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=user . .
USER user

EXPOSE 7860
CMD ["python", "start_node.py", "all", "--host", "0.0.0.0"]
