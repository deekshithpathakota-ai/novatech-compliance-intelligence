"""Load the NovaTech demo dataset.

    python -m scripts.seed                 # apply migrations, seed ONLY if the database is empty (safe to re-run)
    python -m scripts.seed --reset         # DESTRUCTIVE: drop all app tables, re-run migrations, re-seed
    python -m scripts.seed --reset --yes   # required when ENVIRONMENT=production

Uses DATABASE_URL. The schema always comes from the Alembic migrations, so a seeded database and a
migrated database are identical.
"""
import argparse
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database.session import Base, SessionLocal, engine  # noqa: E402

SEED_LOCK = 724_001  # pg advisory lock id: two instances starting together never seed twice


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")


def has_data() -> bool:
    with engine.connect() as c:
        if engine.dialect.name == "postgresql" and not c.execute(text("SELECT to_regclass('public.companies')")).scalar():
            return False
        return c.execute(text("SELECT 1 FROM companies LIMIT 1")).first() is not None


def drop_everything() -> None:
    import app.models  # noqa: F401  (register tables)

    Base.metadata.drop_all(engine)
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS alembic_version"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="drop all application data and re-seed (destructive)")
    ap.add_argument("--yes", action="store_true", help="confirm --reset when ENVIRONMENT=production")
    args = ap.parse_args(argv)
    settings = get_settings()

    if args.reset and settings.is_production and not args.yes:
        print("Refusing to reset a production database without --yes.", file=sys.stderr)
        return 2

    t0 = time.time()
    lock = engine.connect() if engine.dialect.name == "postgresql" else None
    try:
        if lock is not None:
            lock.execute(text("SELECT pg_advisory_lock(:k)"), {"k": SEED_LOCK})
        if args.reset:
            print("Resetting database (dropping all application tables)…")
            drop_everything()
        migrate()
        if has_data():
            print("Demo data already present — nothing to do. Use --reset to wipe and re-seed.")
            return 0
        from app.seed.seeder import seed

        with SessionLocal() as db:
            out = seed(db)
        print(f"Seeded in {time.time() - t0:.1f}s:", out)
        return 0
    finally:
        if lock is not None:
            lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": SEED_LOCK})
            lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
