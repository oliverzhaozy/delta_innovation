"""Route guard. Deny-by-default: every view that isn't explicitly public gets
either @login_required or @require(<policy predicate>).
"""
from functools import wraps

from flask import abort
from flask_login import current_user, login_required


def require(predicate):
    """Guard a view with a policy predicate; anonymous -> login, wrong role -> 403."""

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not predicate(current_user):
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator
