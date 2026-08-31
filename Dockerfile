FROM python:3.11-slim

WORKDIR /app

# System deps (audio/streaming ke liye ffmpeg chahiye pytgcalls ko)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY vc_bot.py .

# Railway PORT env khud inject karta hai, isliye EXPOSE sirf docs ke liye
EXPOSE 8080

CMD ["python", "vc_bot.py"]
