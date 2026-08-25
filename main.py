import logging
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import HOST, OPEN_BROWSER, PORT, POLL_INTERVAL_SECONDS, SEED_DEMO_SOURCE
from app.db import Base, SessionLocal, engine, migrate_schema
from app.models import WatchSource
from app.services.polling import poll_all_sources
from app.web.routes import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("risk_watchlist.main")

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Маяк безопасности")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "web" / "static")), name="static")
app.include_router(router)


def _seed_demo_source_if_empty() -> None:
    """Удобство для первого запуска демо — источник всё равно попадает в
    систему только через явную запись в watchlist, как и любой другой."""
    if not SEED_DEMO_SOURCE:
        return
    db = SessionLocal()
    try:
        if db.query(WatchSource).count() == 0:
            db.add(
                WatchSource(
                    platform_label="Демо-платформа",
                    connector_type="mock",
                    source_identifier="demo-public-channel",
                    display_name="Демо-источник (mock)",
                    added_by="система (демо-сид)",
                    is_active=True,
                )
            )
            db.commit()
            logger.info("Добавлен демо-источник (mock) — watchlist была пустой.")
    finally:
        db.close()


def _poll_loop() -> None:
    while True:
        try:
            poll_all_sources()
        except Exception:
            logger.exception("Необработанная ошибка в цикле опроса — цикл продолжает работу")
        time.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_schema()
    _seed_demo_source_if_empty()

    poll_thread = threading.Thread(target=_poll_loop, daemon=True, name="poll-loop")
    poll_thread.start()
    logger.info("Фоновый опрос запущен, интервал %s сек.", POLL_INTERVAL_SECONDS)

    if OPEN_BROWSER:
        def _open_browser() -> None:
            try:
                webbrowser.open(f"http://{HOST}:{PORT}")
            except Exception:
                logger.warning("Не удалось открыть браузер автоматически — откройте http://%s:%s вручную.", HOST, PORT)

        threading.Timer(1.5, _open_browser).start()

    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
