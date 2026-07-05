from flask import render_template
from flask_login import login_required

from app.blueprints.main import bp


@bp.route("/")
@login_required
def dashboard():
    return render_template("main/dashboard.html")
