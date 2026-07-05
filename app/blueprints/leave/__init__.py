from flask import Blueprint

bp = Blueprint("leave", __name__, url_prefix="/leave")

from app.blueprints.leave import routes  # noqa: E402,F401
