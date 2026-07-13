FROM python:3.12-slim

WORKDIR /app

# Copy all source files
COPY . .

# Create data and logs directories
RUN mkdir -p data logs

# Set Python to run unbuffered
ENV PYTHONUNBUFFERED=1

# Run the bot with exception catching
CMD ["python", "-u", "main.py"]
