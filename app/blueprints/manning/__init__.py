from flask import Blueprint

bp = Blueprint("manning", __name__, url_prefix="/manning")

from app.blueprints.manning import routes  # noqa: E402,F401
