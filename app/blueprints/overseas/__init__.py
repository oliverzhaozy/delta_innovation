from flask import Blueprint

bp = Blueprint("overseas", __name__, url_prefix="/overseas")

from app.blueprints.overseas import routes  # noqa: E402,F401
