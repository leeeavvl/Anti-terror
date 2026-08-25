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

# БД (SQLite) и .env — вне образа, чтобы данные и секреты не терялись/не
# попадали в него при пересборке.
VOLUME ["/app/data"]

CMD ["python", "main.py"]
