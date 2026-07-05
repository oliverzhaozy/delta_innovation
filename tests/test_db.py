from sqlalchemy import text

from app.extensions import db


def _pragma(app, name):
    with app.app_context():
        return db.session.execute(text(f"PRAGMA {name}")).scalar()


def test_foreign_keys_enforced(app):
    # OFF by default in SQLite — a silent data-integrity gotcha if unset.
    assert _pragma(app, "foreign_keys") == 1


def test_busy_timeout_set(app):
    assert _pragma(app, "busy_timeout") == 5000
