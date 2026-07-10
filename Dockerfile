# 1. आधिकारिक स्टेबल पायथन 3.11 इमेज का उपयोग करें
FROM python:3.11-slim

# 2. सिस्टम डिपेंडेंसीज इंस्टॉल करें
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 3. वर्किंग डायरेक्टरी सेट करें
WORKDIR /app

# 4. डिपेंडेंसी लिस्ट को कॉपी करके फ्रेश इंस्टॉल करें
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. बाकी सारा कोड कॉपी करें
COPY . .

# 6. पोर्ट को रेंडर के लिए ओपन करें
EXPOSE 10000

# 7. बोट का कीप-अलाइव सर्वर चालू करें
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "keepalive:app"]
