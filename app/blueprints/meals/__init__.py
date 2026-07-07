from flask import Blueprint

bp = Blueprint("meals", __name__, url_prefix="/meals")

from app.blueprints.meals import routes  # noqa: E402,F401
