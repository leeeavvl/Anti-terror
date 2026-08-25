from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DB_PATH


class Base(DeclarativeBase):
    pass


engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"timeout": 30, "check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_schema() -> None:
    """Лёгкая миграция без Alembic — на масштабе этого проекта (SQLite,
    одна БД) добавление недостающих колонок вручную проще и понятнее, чем
    подключать полноценный инструмент миграций. Base.metadata.create_all()
    создаёт только отсутствующие ТАБЛИЦЫ, но не добавляет колонки в уже
    существующие — это и делает эта функция, безопасно (IF NOT EXISTS по
    факту, через проверку PRAGMA table_info)."""

    with engine.connect() as conn:
        posts_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(posts)")}
        if "has_media" not in posts_columns:
            conn.exec_driver_sql("ALTER TABLE posts ADD COLUMN has_media BOOLEAN DEFAULT 0")
            conn.commit()

        marker_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(custom_markers)")}
        if marker_columns:  # таблица уже существовала до добавления новых полей
            for column, ddl in (
                ("category_title", "ALTER TABLE custom_markers ADD COLUMN category_title TEXT DEFAULT ''"),
                ("source", "ALTER TABLE custom_markers ADD COLUMN source TEXT DEFAULT ''"),
                ("note", "ALTER TABLE custom_markers ADD COLUMN note TEXT DEFAULT ''"),
            ):
                if column not in marker_columns:
                    conn.exec_driver_sql(ddl)
                    conn.commit()
