from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user

from app.extensions import db
from app.forms import LoginForm
from app.models.user import User
from app.models.audit import AuditLog

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.strip().lower()).first()
        if user is None or not user.check_password(form.password.data):
            flash("이메일 또는 비밀번호가 올바르지 않습니다.", "danger")
        elif not user.is_active:
            flash("비활성화된 계정입니다. 관리자에게 문의하세요.", "danger")
        else:
            from datetime import datetime, timezone

            login_user(user)
            user.last_login_at = datetime.now(timezone.utc)
            AuditLog.record(user, None, "login", "User", user.id, detail=f"{user.email} 로그인", ip_address=request.remote_addr)
            db.session.commit()
            next_url = request.args.get("next")
            return redirect(next_url or url_for("main.index"))
    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    AuditLog.record(current_user, None, "logout", "User", current_user.id, detail=f"{current_user.email} 로그아웃", ip_address=request.remote_addr)
    db.session.commit()
    logout_user()
    flash("로그아웃되었습니다.", "info")
    return redirect(url_for("auth.login"))
