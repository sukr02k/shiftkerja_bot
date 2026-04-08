FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data

ENV TELEGRAM_BOT_TOKEN=""
ENV DB_PATH="/data/schedules.db"

CMD ["python", "bot.py"]