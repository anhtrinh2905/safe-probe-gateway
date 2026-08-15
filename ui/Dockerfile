# Build context is the REPO ROOT, not ui/ -- this image needs src/safe_probe/
# alongside ui/, and that lives outside this directory. On Railway: point the
# service at the repo root with this file as the Dockerfile path (ui/Dockerfile).
FROM python:3.11-slim

WORKDIR /app

COPY ui/requirements.txt ui/requirements.txt
RUN pip install --no-cache-dir -r ui/requirements.txt

# Only the library the demo depends on -- not gateway/, not targets/.
COPY src/safe_probe src/safe_probe
COPY ui ui

ENV PYTHONPATH=/app/src
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

EXPOSE 8501
# Shell form so $PORT (injected by Railway) is expanded; falls back to 8501
# for `docker run` without it.
CMD streamlit run ui/streamlit_app.py --server.port=${PORT:-8501} --server.address=0.0.0.0
