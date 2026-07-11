FROM python:3.11-slim

WORKDIR /app

# Create data directory for persistent SQLite
RUN mkdir -p /app/data

COPY requirements.txt .

# पैकेजेस को सीधे फ़ोर्स इंस्टॉल करें
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir smartapi-python pyotp Flask requests gunicorn python-telegram-bot

COPY . .

# Expose port
EXPOSE 8080

# keepalive और आपके मुख्य बोट को एक साथ बैकग्राउंड में चलाने के लिए
CMD python keepalive.py & python app.py
