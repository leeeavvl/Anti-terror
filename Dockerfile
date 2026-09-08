FROM python:3.12-slim

WORKDIR /app

# Сначала только зависимости — слой кэшируется, пересборка при правках кода
# не переустанавливает пакеты заново.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# В контейнере слушать нужно 0.0.0.0 (иначе порт наружу не пробросится), и
# открывать браузер автоматически там некому и не на чем.
ENV HOST=0.0.0.0 \
    PORT=8000 \
    OPEN_BROWSER=0 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# БД (SQLite) хранится в /app/data — вне образа, чтобы данные не терялись при
# пересборке. Инструкция VOLUME здесь намеренно не используется (Railway
# отклоняет её при сборке) — постоянное хранилище подключается снаружи:
# `docker run -v ...` локально, или Railway Volume, примонтированный на
# /app/data через настройки проекта на railway.app.
CMD ["python", "main.py"]
