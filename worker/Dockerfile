FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY worker/requirements.txt ./requirements.txt

RUN python -m pip install --no-cache-dir -r requirements.txt

COPY worker/worker.py ./worker.py

CMD ["python", "worker.py"]
