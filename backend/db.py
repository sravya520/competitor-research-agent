from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session

from backend import config
from backend.models import Base

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        # pre_ping: free Postgres hosts (Neon) suspend idle connections.
        _engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
        if _engine.dialect.name == "sqlite":

            @event.listens_for(_engine, "connect")
            def _fk_on(dbapi_conn, _):  # SQLite ignores foreign keys unless asked
                dbapi_conn.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(_engine)
        _add_missing_columns(_engine)
    return _engine


def _add_missing_columns(engine) -> None:
    """create_all makes new tables but never alters existing ones; add any new columns here.

    ponytail: additive only (no renames or type changes). Add Alembic when we need more than that.
    """
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(dialect=engine.dialect)}"
                if col.server_default is not None:
                    arg = str(col.server_default.arg)
                    # Numbers go in bare; text must be quoted or Postgres reads it as a column name
                    # (SQLite forgives the bare form, which is why a SQLite-only test would not catch it).
                    ddl += f" DEFAULT {arg if arg.lstrip('-').isdigit() else repr(arg)}"
                conn.execute(text(ddl))


@contextmanager
def session():
    """Commit on success, roll back on error."""
    with Session(get_engine(), expire_on_commit=False) as s:
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
