from flask import Blueprint, render_template
from flask_login import login_required, current_user

from app.models.study import Study, StudyMembership

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required
def index():
    if current_user.is_platform_admin:
        studies = Study.query.order_by(Study.created_at.desc()).all()
        my_roles = {s.id: "platform_admin" for s in studies}
    else:
        memberships = StudyMembership.query.filter_by(user_id=current_user.id).all()
        studies = [m.study for m in memberships]
        my_roles = {m.study_id: m.role for m in memberships}
    return render_template("index.html", studies=studies, my_roles=my_roles)
