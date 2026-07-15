FROM python:3.12-slim

WORKDIR /app

COPY . .

RUN mkdir -p data logs

ENV PYTHONUNBUFFERED=1

CMD ["python", "-u", "main.py"]
