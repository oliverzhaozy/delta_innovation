from flask import Flask, render_template

from app.extensions import csrf, db, limiter, login_manager, migrate
from config import get_config


def create_app(config_class=None):
    """App factory — per-test app instances and a clean dev/test/prod split."""
    config_class = config_class or get_config()
    app = Flask(__name__)
    app.config.from_object(config_class)
    config_class.validate(app)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from app import models  # noqa: F401  register tables with SQLAlchemy metadata
    from app.cli import register_cli

    register_cli(app)

    from app.blueprints.admin import bp as admin_bp
    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.main import bp as main_bp

    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    from app.domain import policy

    @app.context_processor
    def inject_policy():
        # Templates condition nav/content on the same predicates routes enforce.
        return {"policy": policy}

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("errors/403.html"), 403

    @app.template_filter("days")
    def fmt_half_days(half_days):
        # Ledger stores integer half-days; people think in days: 5 -> "2.5".
        return f"{half_days / 2:g}"

    @app.route("/health")
    def health():
        return {"status": "ok"}

    return app
