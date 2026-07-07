from flask import Blueprint

bp = Blueprint("ro", __name__, url_prefix="/ro")

from app.blueprints.ro import routes  # noqa: E402,F401
