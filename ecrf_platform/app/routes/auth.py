import os

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
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


@auth_bp.route("/setup", methods=["GET", "POST"])
def initial_setup():
    """터미널 명령 없이 브라우저에서만 최초 플랫폼 관리자 계정을 만들기 위한 1회용 화면."""
    if User.query.filter_by(is_platform_admin=True).first():
        abort(404)

    required_key = os.environ.get("SETUP_ADMIN_KEY", "")
    error = None

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        setup_key = request.form.get("setup_key", "")

        if required_key and setup_key != required_key:
            error = "설정 키(Setup Key)가 올바르지 않습니다."
        elif not name or not email or not password:
            error = "이름, 이메일, 비밀번호를 모두 입력해주세요."
        elif len(password) < 8:
            error = "비밀번호는 8자 이상으로 설정해주세요."
        elif User.query.filter_by(email=email).first():
            error = "이미 사용 중인 이메일입니다."
        else:
            db.create_all()
            user = User(name=name, email=email, is_platform_admin=True)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            AuditLog.record(user, None, "create", "User", user.id, detail=f"최초 관리자 계정 생성(웹 설정): {email}", ip_address=request.remote_addr)
            db.session.commit()
            flash("관리자 계정이 생성되었습니다. 이제 로그인해주세요.", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/setup.html", error=error, key_required=bool(required_key))
