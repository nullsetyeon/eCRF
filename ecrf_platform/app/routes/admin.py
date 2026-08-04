import re
import json

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import login_required, current_user

from app.extensions import db
from app.access import platform_admin_required, require_study_admin
from app.forms import StudyForm, InviteMemberForm, VisitForm, FormTemplateForm
from app.models.study import Study, StudyMembership, ROLE_CHOICES, ROLE_STUDY_ADMIN
from app.models.form import Visit, FormTemplate, Field, FIELD_TYPES, FIELD_TYPES_WITH_OPTIONS
from app.models.user import User
from app.models.audit import AuditLog
from app.safe_eval import evaluate_formula, FormulaError

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

VARIABLE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")


# ---------------------------------------------------------------- 연구(Study)
@admin_bp.route("/studies", methods=["GET", "POST"])
@login_required
@platform_admin_required
def studies():
    form = StudyForm()
    if form.validate_on_submit():
        code = form.code.data.strip()
        if Study.query.filter_by(code=code).first():
            flash("이미 사용 중인 연구 코드입니다.", "danger")
        else:
            study = Study(name=form.name.data.strip(), code=code, description=form.description.data, created_by_id=current_user.id)
            db.session.add(study)
            db.session.flush()
            db.session.add(StudyMembership(study_id=study.id, user_id=current_user.id, role=ROLE_STUDY_ADMIN))
            AuditLog.record(current_user, study.id, "create", "Study", study.id, detail=f"연구 생성: {study.name}", ip_address=request.remote_addr)
            db.session.commit()
            flash(f"연구 '{study.name}'가 생성되었습니다.", "success")
            return redirect(url_for("admin.study_detail", study_id=study.id))
    all_studies = Study.query.order_by(Study.created_at.desc()).all()
    return render_template("admin/studies.html", form=form, studies=all_studies)


@admin_bp.route("/studies/<int:study_id>")
@login_required
def study_detail(study_id):
    study = db.get_or_404(Study, study_id)
    require_study_admin(study_id)
    return render_template("admin/study_detail.html", study=study)


# ---------------------------------------------------------------- 연구원 초대/권한
@admin_bp.route("/studies/<int:study_id>/members", methods=["GET", "POST"])
@login_required
def members(study_id):
    study = db.get_or_404(Study, study_id)
    require_study_admin(study_id)

    form = InviteMemberForm()
    form.role.choices = ROLE_CHOICES
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = User.query.filter_by(email=email).first()
        created_new = False
        if user is None:
            temp_pw = form.temp_password.data or "changeme123!"
            user = User(name=form.name.data.strip(), email=email)
            user.set_password(temp_pw)
            db.session.add(user)
            db.session.flush()
            created_new = True
        existing = StudyMembership.query.filter_by(study_id=study.id, user_id=user.id).first()
        if existing:
            existing.role = form.role.data
            flash(f"{user.email} 님의 권한을 변경했습니다.", "info")
        else:
            db.session.add(StudyMembership(study_id=study.id, user_id=user.id, role=form.role.data))
            flash(f"{user.email} 님을 연구에 초대했습니다." + (" (신규 계정 생성됨 - 임시 비밀번호를 직접 전달해주세요)" if created_new else ""), "success")
        AuditLog.record(current_user, study.id, "update", "StudyMembership", user.id, detail=f"{email} 초대/권한변경 -> {form.role.data}", ip_address=request.remote_addr)
        db.session.commit()
        return redirect(url_for("admin.members", study_id=study.id))

    return render_template("admin/members.html", study=study, form=form)


@admin_bp.route("/studies/<int:study_id>/members/<int:membership_id>/remove", methods=["POST"])
@login_required
def remove_member(study_id, membership_id):
    require_study_admin(study_id)
    m = db.get_or_404(StudyMembership, membership_id)
    if m.study_id != study_id:
        abort(404)
    AuditLog.record(current_user, study_id, "delete", "StudyMembership", m.user_id, detail=f"{m.user.email} 접근권한 제거", ip_address=request.remote_addr)
    db.session.delete(m)
    db.session.commit()
    flash("접근 권한을 제거했습니다.", "info")
    return redirect(url_for("admin.members", study_id=study_id))


# ---------------------------------------------------------------- 방문(Visit) 스케줄
@admin_bp.route("/studies/<int:study_id>/visits", methods=["GET", "POST"])
@login_required
def visits(study_id):
    study = db.get_or_404(Study, study_id)
    require_study_admin(study_id)

    form = VisitForm()
    if form.validate_on_submit():
        max_order = db.session.query(db.func.max(Visit.order_index)).filter_by(study_id=study.id).scalar() or 0
        v = Visit(
            study_id=study.id,
            name=form.name.data.strip(),
            window_description=form.window_description.data,
            allow_repeat=form.allow_repeat.data,
            order_index=max_order + 1,
        )
        db.session.add(v)
        AuditLog.record(current_user, study.id, "create", "Visit", None, detail=f"방문 추가: {v.name}", ip_address=request.remote_addr)
        db.session.commit()
        flash(f"방문 '{v.name}'을(를) 추가했습니다.", "success")
        return redirect(url_for("admin.visits", study_id=study.id))

    return render_template("admin/visits.html", study=study, form=form)


@admin_bp.route("/visits/<int:visit_id>/edit", methods=["GET", "POST"])
@login_required
def edit_visit(visit_id):
    visit = db.get_or_404(Visit, visit_id)
    require_study_admin(visit.study_id)
    form = VisitForm(obj=visit)
    if form.validate_on_submit():
        visit.name = form.name.data.strip()
        visit.window_description = form.window_description.data
        visit.allow_repeat = form.allow_repeat.data
        AuditLog.record(current_user, visit.study_id, "update", "Visit", visit.id, detail=f"방문 수정: {visit.name}", ip_address=request.remote_addr)
        db.session.commit()
        flash("방문 정보를 수정했습니다.", "success")
        return redirect(url_for("admin.visits", study_id=visit.study_id))
    return render_template("admin/edit_visit.html", visit=visit, form=form)


@admin_bp.route("/visits/<int:visit_id>/delete", methods=["POST"])
@login_required
def delete_visit(visit_id):
    visit = db.get_or_404(Visit, visit_id)
    require_study_admin(visit.study_id)
    study_id = visit.study_id
    AuditLog.record(current_user, study_id, "delete", "Visit", visit.id, detail=f"방문 삭제: {visit.name}", ip_address=request.remote_addr)
    db.session.delete(visit)
    db.session.commit()
    flash("방문을 삭제했습니다. (해당 방문에 연결된 폼/데이터도 함께 삭제됩니다)", "warning")
    return redirect(url_for("admin.visits", study_id=study_id))


@admin_bp.route("/visits/<int:visit_id>/move", methods=["POST"])
@login_required
def move_visit(visit_id):
    visit = db.get_or_404(Visit, visit_id)
    require_study_admin(visit.study_id)
    direction = request.form.get("direction")
    siblings = Visit.query.filter_by(study_id=visit.study_id).order_by(Visit.order_index).all()
    idx = siblings.index(visit)
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if 0 <= swap_idx < len(siblings):
        siblings[idx].order_index, siblings[swap_idx].order_index = siblings[swap_idx].order_index, siblings[idx].order_index
        db.session.commit()
    return redirect(url_for("admin.visits", study_id=visit.study_id))


# ---------------------------------------------------------------- 폼(FormTemplate)
@admin_bp.route("/studies/<int:study_id>/forms", methods=["GET", "POST"])
@login_required
def forms_list(study_id):
    study = db.get_or_404(Study, study_id)
    require_study_admin(study_id)

    form = FormTemplateForm()
    form.visit_id.choices = [(0, "-- 방문 비종속 (반복기록폼 등) --")] + [(v.id, v.name) for v in study.visits]
    if form.validate_on_submit():
        max_order = db.session.query(db.func.max(FormTemplate.order_index)).filter_by(study_id=study.id).scalar() or 0
        ft = FormTemplate(
            study_id=study.id,
            visit_id=form.visit_id.data or None,
            name=form.name.data.strip(),
            is_repeating=form.is_repeating.data,
            order_index=max_order + 1,
        )
        db.session.add(ft)
        AuditLog.record(current_user, study.id, "create", "FormTemplate", None, detail=f"폼 추가: {ft.name}", ip_address=request.remote_addr)
        db.session.commit()
        flash(f"폼 '{ft.name}'을(를) 추가했습니다. 이제 문항을 설계해주세요.", "success")
        return redirect(url_for("admin.form_builder", form_id=ft.id))

    forms_by_visit = {}
    unbound = []
    for f in FormTemplate.query.filter_by(study_id=study.id).order_by(FormTemplate.order_index).all():
        if f.visit_id:
            forms_by_visit.setdefault(f.visit_id, []).append(f)
        else:
            unbound.append(f)
    return render_template("admin/forms_list.html", study=study, form=form, forms_by_visit=forms_by_visit, unbound=unbound)


@admin_bp.route("/forms/<int:form_id>/delete", methods=["POST"])
@login_required
def delete_form(form_id):
    ft = db.get_or_404(FormTemplate, form_id)
    require_study_admin(ft.study_id)
    study_id = ft.study_id
    AuditLog.record(current_user, study_id, "delete", "FormTemplate", ft.id, detail=f"폼 삭제: {ft.name}", ip_address=request.remote_addr)
    db.session.delete(ft)
    db.session.commit()
    flash("폼을 삭제했습니다.", "warning")
    return redirect(url_for("admin.forms_list", study_id=study_id))


# ---------------------------------------------------------------- 필드(문항) 빌더
def _parse_options_text(text):
    """'값|라벨' 또는 '라벨' 한 줄씩 입력받아 옵션 리스트로 변환."""
    options = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            value, label = line.split("|", 1)
        else:
            value, label = line, line
        options.append({"value": value.strip(), "label": label.strip()})
    return options


def _options_to_text(options):
    return "\n".join(f"{o['value']}|{o['label']}" for o in options)


@admin_bp.route("/forms/<int:form_id>/builder")
@login_required
def form_builder(form_id):
    ft = db.get_or_404(FormTemplate, form_id)
    require_study_admin(ft.study_id)
    return render_template("admin/form_builder.html", ft=ft, field_types=FIELD_TYPES, options_types=FIELD_TYPES_WITH_OPTIONS)


@admin_bp.route("/forms/<int:form_id>/fields/new", methods=["POST"])
@login_required
def new_field(form_id):
    ft = db.get_or_404(FormTemplate, form_id)
    require_study_admin(ft.study_id)
    return _save_field(ft, None)


@admin_bp.route("/fields/<int:field_id>/edit", methods=["GET", "POST"])
@login_required
def edit_field(field_id):
    field = db.get_or_404(Field, field_id)
    ft = field.form
    require_study_admin(ft.study_id)
    if request.method == "POST":
        return _save_field(ft, field)
    other_fields = [f for f in ft.fields if f.id != field.id]
    return render_template(
        "admin/edit_field.html",
        field=field,
        ft=ft,
        field_types=FIELD_TYPES,
        options_types=FIELD_TYPES_WITH_OPTIONS,
        options_text=_options_to_text(field.get_options()),
        branch=field.get_branch_condition() or {},
        other_fields=other_fields,
    )


def _save_field(ft, field):
    variable_name = request.form.get("variable_name", "").strip()
    label = request.form.get("label", "").strip()
    field_type = request.form.get("field_type", "text")
    help_text = request.form.get("help_text", "").strip() or None
    unit = request.form.get("unit", "").strip() or None
    required = request.form.get("required") == "on"
    options_text = request.form.get("options_text", "")
    calc_formula = request.form.get("calc_formula", "").strip() or None

    branch_field = request.form.get("branch_field", "")
    branch_op = request.form.get("branch_op", "eq")
    branch_value = request.form.get("branch_value", "")

    errors = []
    if not variable_name or not VARIABLE_RE.match(variable_name):
        errors.append("변수명은 영문자로 시작하고 영문/숫자/밑줄만 사용할 수 있습니다.")
    if not label:
        errors.append("문항 라벨(질문 내용)을 입력해주세요.")

    duplicate = ft.field_by_variable(variable_name)
    if duplicate and (field is None or duplicate.id != field.id):
        errors.append(f"변수명 '{variable_name}'은(는) 이미 이 폼에서 사용 중입니다.")

    if field_type == "calculated":
        if not calc_formula:
            errors.append("자동 계산 필드는 계산식을 입력해야 합니다.")
        else:
            dummy_vars = {f.variable_name: 1 for f in ft.fields if f.field_type != "calculated"}
            dummy_vars[variable_name] = 1
            try:
                evaluate_formula(calc_formula, dummy_vars)
            except FormulaError as e:
                errors.append(f"계산식 오류: {e}")
            except ZeroDivisionError:
                pass  # 문법 자체는 유효하므로 통과

    if errors:
        for e in errors:
            flash(e, "danger")
        if field is None:
            return redirect(url_for("admin.form_builder", form_id=ft.id))
        return redirect(url_for("admin.edit_field", field_id=field.id))

    if field is None:
        max_order = db.session.query(db.func.max(Field.order_index)).filter_by(form_id=ft.id).scalar() or 0
        field = Field(form_id=ft.id, order_index=max_order + 1)
        db.session.add(field)
        action = "create"
    else:
        action = "update"

    field.variable_name = variable_name
    field.label = label
    field.field_type = field_type
    field.help_text = help_text
    field.unit = unit
    field.required = required
    field.calc_formula = calc_formula if field_type == "calculated" else None

    if field_type in FIELD_TYPES_WITH_OPTIONS:
        field.set_options(_parse_options_text(options_text))
    else:
        field.options_json = None

    if branch_field:
        field.set_branch_condition({"field": branch_field, "op": branch_op, "value": branch_value})
    else:
        field.set_branch_condition(None)

    AuditLog.record(current_user, ft.study_id, action, "Field", field.id, detail=f"문항 {action}: {field.variable_name} ({field.label})", ip_address=request.remote_addr)
    db.session.commit()
    flash("문항을 저장했습니다.", "success")
    return redirect(url_for("admin.form_builder", form_id=ft.id))


@admin_bp.route("/fields/<int:field_id>/delete", methods=["POST"])
@login_required
def delete_field(field_id):
    field = db.get_or_404(Field, field_id)
    require_study_admin(field.form.study_id)
    form_id = field.form_id
    AuditLog.record(current_user, field.form.study_id, "delete", "Field", field.id, detail=f"문항 삭제: {field.variable_name}", ip_address=request.remote_addr)
    db.session.delete(field)
    db.session.commit()
    flash("문항을 삭제했습니다.", "warning")
    return redirect(url_for("admin.form_builder", form_id=form_id))


@admin_bp.route("/forms/<int:form_id>/fields/reorder", methods=["POST"])
@login_required
def reorder_fields(form_id):
    ft = db.get_or_404(FormTemplate, form_id)
    require_study_admin(ft.study_id)
    payload = request.get_json(silent=True) or {}
    ordered_ids = payload.get("field_ids", [])
    id_to_field = {f.id: f for f in ft.fields}
    for idx, fid in enumerate(ordered_ids):
        if fid in id_to_field:
            id_to_field[fid].order_index = idx
    db.session.commit()
    return jsonify({"ok": True})
