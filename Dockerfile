FROM python:3.11-slim

# System dependencies (ffmpeg, git, compilers)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    python3-dev \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pehle requirements install karo (telethon, numpy, aiohttp)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 🔥 Ab GitHub se pytgcalls install karo (latest master)
RUN pip install --no-cache-dir git+https://github.com/pytgcalls/pytgcalls.git

# Bot code copy karo
COPY bot.py .

# Run
CMD ["python", "bot.py"]
