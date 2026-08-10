FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY policy.py app.py ./
# policy.yml is bind-mounted by docker-compose so editing the allowlist does not
# mean rebuilding the image -- policy is data, and data should be reloadable.
COPY policy.yml ./

EXPOSE 8000
# One worker on purpose: the rate limiter keeps its buckets in memory, and two
# workers would silently double the effective limit.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
