from flask import Blueprint

bp = Blueprint("parade", __name__, url_prefix="/parade")

from app.blueprints.parade import routes  # noqa: E402,F401
