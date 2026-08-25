FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY python/ ./python/
COPY assets/ ./assets/

ENV STEAMGIFTS_DATA_DIR=/data
ENV HOST=0.0.0.0
ENV PORT=8765
ENV PYTHONUNBUFFERED=1

VOLUME ["/data"]
EXPOSE 8765

WORKDIR /app/python
CMD ["python", "web_main.py"]
