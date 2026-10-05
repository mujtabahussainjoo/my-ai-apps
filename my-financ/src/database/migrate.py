"""``python -m src.database.migrate`` - apply or inspect schema migrations.

    python -m src.database.migrate              # apply pending
    python -m src.database.migrate --status     # what is applied
    python -m src.database.migrate --reset      # DROP everything (dev only)

``--reset`` destroys every table in the database, so it requires both an
explicit flag and a typed confirmation. There is no half-measure here: a
trading ledger that is only partly dropped is worse than one that is intact.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import inspect, text

from src.core.config import get_settings
from src.core.logging import configure_logging, get_logger
from src.database.migrations import status, upgrade
from src.database.models import Base  # noqa: F401 - registers the metadata
from src.database.session import build_engine

logger = get_logger(__name__)


def show_status(engine) -> None:
    rows = status(engine)
    if not rows:
        print("no migrations found")
        return
    width = max(len(name) for _, name, _ in rows)
    for version, name, applied in rows:
        mark = "applied" if applied else "pending"
        print(f"  {version:<6} {name:<{width}}  {mark}")


def do_reset(engine) -> bool:
    settings = get_settings()
    if settings.trading_mode == "live":
        print(
            "refusing to reset while TRADING_MODE=live; "
            "point at a scratch database instead",
            file=sys.stderr,
        )
        return False

    tables = sorted(inspect(engine).get_table_names())
    destructive = [t for t in tables if t != "schema_migrations"]
    if not destructive:
        print("nothing to reset")
        return True

    print(f"about to DROP {len(destructive)} tables and all their data:")
    print(f"  {', '.join(destructive)}")
    if input("type 'reset' to confirm: ").strip().lower() != "reset":
        print("aborted")
        return False

    # Drop in reverse dependency order so foreign keys never block a drop.
    Base.metadata.drop_all(bind=engine, checkfirst=True)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS schema_migrations"))
    logger.info("database_reset")
    print("dropped; run again without --reset to recreate")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="list migrations and exit")
    parser.add_argument("--reset", action="store_true", help="drop every table (destructive)")
    parser.add_argument("--database-url", default=None, help="override the configured URL")
    args = parser.parse_args(argv)

    configure_logging()
    settings = get_settings()
    engine = build_engine(args.database_url)

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        print(f"cannot reach the database: {exc}", file=sys.stderr)
        print(f"url host: {settings.postgres_host}:{settings.postgres_port}", file=sys.stderr)
        return 1

    if args.reset:
        return 0 if do_reset(engine) else 1

    if args.status:
        show_status(engine)
        return 0

    try:
        applied = upgrade(engine)
    except RuntimeError as exc:
        print(f"migration refused: {exc}", file=sys.stderr)
        return 1
    if applied:
        print(f"applied {len(applied)} migration(s): {', '.join(applied)}")
    else:
        print("schema is up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())