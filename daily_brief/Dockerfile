FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY daily_brief ./daily_brief

# Google token and run logs live on a bind mount so they survive rebuilds.
ENV DB_DATA_DIR=/data
CMD ["python", "-m", "daily_brief", "serve"]
