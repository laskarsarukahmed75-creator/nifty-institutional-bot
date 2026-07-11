FROM python:3.11-slim

WORKDIR /app

# SQLite डेटाबेस के लिए डायरेक्टरी बनाएँ
RUN mkdir -p /app/data

COPY requirements.txt .

# ज़रूरी पैकेजेस को फ़ोर्स इंस्टॉल करें
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir smartapi-python pyotp Flask requests gunicorn python-telegram-bot

COPY . .

# पोर्ट 8080 को ओपन करें (फ्री सर्विस के लिए ज़रूरी है)
EXPOSE 8080

# Gunicorn के ज़रिए keepalive को चलाएँ जो रेंडर को खुश रखेगा
CMD ["gunicorn", "keepalive:app", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4"]
