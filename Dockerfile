# 1. Base Image: Python 3.12 ka official lightweight version
FROM python:3.12-slim

# 2. Working Directory: System ke andar 'app' naam ka folder banana
WORKDIR /app

# 3. Environment Variables: Render container ke liye timezone IST set karna
ENV TZ=Asia/Kolkata
ENV PYTHONUNBUFFERED=1

# 4. Copy Code: Aapki saari absolute python files ko container me daalna
COPY . .

# 5. Execution Command: Supervisor thread watchdog ko boot up karna
CMD ["python", "main.py"]
