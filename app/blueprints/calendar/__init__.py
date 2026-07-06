from flask import Blueprint

# Package name doesn't shadow stdlib `calendar` — Python's absolute imports
# mean `import calendar` inside this file would still resolve to the stdlib.
bp = Blueprint("calendar", __name__, url_prefix="/calendar")

from app.blueprints.calendar import routes  # noqa: E402,F401
