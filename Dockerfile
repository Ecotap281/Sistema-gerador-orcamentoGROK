FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PORT=10000

RUN apt-get update && apt-get install -y --no-install-recommends     libpango-1.0-0     libpangoft2-1.0-0     libcairo2     libgdk-pixbuf-2.0-0     libffi-dev     shared-mime-info     fonts-dejavu-core     && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/generated /app/data

CMD gunicorn --bind 0.0.0.0:$PORT app:app
