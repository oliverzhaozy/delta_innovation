from flask import Blueprint

bp = Blueprint("ledger", __name__, url_prefix="/ledger")

from app.blueprints.ledger import routes  # noqa: E402,F401
