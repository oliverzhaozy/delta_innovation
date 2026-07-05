from flask import Flask

from app.extensions import db, migrate
from config import get_config


def create_app(config_class=None):
    """App factory — per-test app instances and a clean dev/test/prod split."""
    config_class = config_class or get_config()
    app = Flask(__name__)
    app.config.from_object(config_class)
    config_class.validate(app)

    db.init_app(app)
    migrate.init_app(app, db)

    from app import models  # noqa: F401  register tables with SQLAlchemy metadata
    from app.cli import register_cli

    register_cli(app)

    @app.route("/health")
    def health():
        return {"status": "ok"}

    @app.route("/")
    def index():
        # Placeholder until the dashboard lands in P0.5.
        return "Ops Portal is up."

    return app
