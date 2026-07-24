from flask import Blueprint

bp = Blueprint("dev", __name__, url_prefix="/dev")

from app.blueprints.dev import routes  # noqa: E402,F401
