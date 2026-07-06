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
    from app.blueprints.calendar import bp as calendar_bp
    from app.blueprints.leave import bp as leave_bp
    from app.blueprints.ledger import bp as ledger_bp
    from app.blueprints.main import bp as main_bp
    from app.blueprints.overseas import bp as overseas_bp
    from app.blueprints.parade import bp as parade_bp

    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(leave_bp)
    app.register_blueprint(ledger_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(overseas_bp)
    app.register_blueprint(parade_bp)

    from app.domain import policy, routing
    from app.domain.types import BalanceKind

    @app.context_processor
    def inject_policy():
        # Templates condition nav/content on the same predicates routes enforce.
        return {"policy": policy, "routing": routing, "BalanceKind": BalanceKind}

    @app.context_processor
    def inject_pending_badge():
        # No notifications by design — the nav badge is how approvers find work.
        from flask_login import current_user

        from app.domain.types import RequestStatus
        from app.models import LeaveRequest, Person

        if not current_user.is_authenticated:
            return {}
        if policy.is_pc(current_user):
            count = (
                db.session.query(LeaveRequest.id)
                .join(Person, LeaveRequest.person_id == Person.id)
                .filter(
                    LeaveRequest.status == RequestStatus.PENDING_PC,
                    Person.platoon == current_user.platoon,
                )
                .count()
            )
        elif policy.can_final_approve(current_user):
            count = (
                db.session.query(LeaveRequest.id)
                .filter(LeaveRequest.status == RequestStatus.PENDING_OC)
                .count()
            )
        else:
            return {}
        return {"pending_approvals": count}

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
