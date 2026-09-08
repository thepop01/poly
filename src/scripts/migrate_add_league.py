"""Validate the database URL and delegate schema changes to Alembic.

The historical script issued unconditional schema statements.
This compatibility entry point now performs no schema mutation itself.  Use
``python -m src.scripts.migrate_add_league`` to run ``alembic upgrade head``;
the migration is replayable on both clean and league-modified databases.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
_ALLOWED_SCHEMES = {"postgresql", "postgres", "postgresql+asyncpg", "postgresql+psycopg2"}


def _database_url() -> str:
    load_dotenv(ROOT / ".env")
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        raise SystemExit("DATABASE_URL is required; no credentials are embedded")
    parsed = urlsplit(value)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise SystemExit("DATABASE_URL must use a PostgreSQL scheme")
    if not parsed.hostname or not parsed.path.strip("/"):
        raise SystemExit("DATABASE_URL must include a PostgreSQL host and database")
    return value


def migrate(argv: list[str] | None = None) -> int:
    """Validate configuration, then execute Alembic's canonical upgrade.

    Extra arguments are passed to Alembic after ``upgrade head`` so existing
    operator wrappers can still add Alembic flags.  No credentials are logged.
    """
    database_url = _database_url()
    args = ["-m", "alembic", "upgrade", "head"]
    if argv:
        raise SystemExit("unsupported arguments; migration only supports upgrade head")
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    return subprocess.call([sys.executable, *args], cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(migrate(sys.argv[1:]))
