FROM python:3.11-slim

WORKDIR /app

RUN mkdir -p /app/data

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir smartapi-python pyotp Flask requests gunicorn python-telegram-bot

COPY . .

# सीधे मुख्य बोट को चलाएं
CMD ["python", "app.py"]
