import csv
import io
import json
import zipfile
from datetime import datetime, timezone

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, send_file
from flask_login import login_required, current_user

from app.extensions import db
from app.access import require_study_access
from app.forms import SubjectForm, VisitInstanceForm
from app.models.study import Study
from app.models.form import Visit, FormTemplate, Field
from app.models.subject import Subject, VisitInstance, ResponseRecord, ResponseValue
from app.models.audit import AuditLog
from app.safe_eval import evaluate_formula, FormulaError

researcher_bp = Blueprint("researcher", __name__, url_prefix="/studies")


# ---------------------------------------------------------------- 대상자
@researcher_bp.route("/<int:study_id>/subjects", methods=["GET", "POST"])
@login_required
def subjects(study_id):
    study = db.get_or_404(Study, study_id)
    require_study_access(study_id)

    form = SubjectForm()
    if form.validate_on_submit():
        code = form.subject_code.data.strip()
        if Subject.query.filter_by(study_id=study.id, subject_code=code).first():
            flash("이미 등록된 대상자 등록번호입니다.", "danger")
        else:
            subj = Subject(study_id=study.id, subject_code=code, memo=form.memo.data, created_by_id=current_user.id)
            db.session.add(subj)
            db.session.flush()
            AuditLog.record(current_user, study.id, "create", "Subject", subj.id, detail=f"대상자 등록: {code}", ip_address=request.remote_addr)
            db.session.commit()
            flash(f"대상자 '{code}'를 등록했습니다.", "success")
            return redirect(url_for("researcher.subject_detail", study_id=study.id, subject_id=subj.id))

    subject_list = Subject.query.filter_by(study_id=study.id).order_by(Subject.created_at.desc()).all()
    return render_template("researcher/subjects.html", study=study, form=form, subjects=subject_list)


@researcher_bp.route("/<int:study_id>/subjects/<int:subject_id>")
@login_required
def subject_detail(study_id, subject_id):
    study = db.get_or_404(Study, study_id)
    require_study_access(study_id)
    subject = db.get_or_404(Subject, subject_id)
    if subject.study_id != study_id:
        abort(404)

    visit_rows = []
    for visit in study.visits:
        instances = [vi for vi in subject.visit_instances if vi.visit_id == visit.id]
        forms_here = FormTemplate.query.filter_by(study_id=study.id, visit_id=visit.id).order_by(FormTemplate.order_index).all()
        visit_rows.append({"visit": visit, "instances": instances, "forms": forms_here})

    unbound_forms = FormTemplate.query.filter_by(study_id=study.id, visit_id=None).order_by(FormTemplate.order_index).all()
    unbound_counts = {
        ft.id: ResponseRecord.query.filter_by(subject_id=subject.id, form_id=ft.id, visit_instance_id=None).count()
        for ft in unbound_forms
    }

    return render_template(
        "researcher/subject_detail.html",
        study=study,
        subject=subject,
        visit_rows=visit_rows,
        unbound_forms=unbound_forms,
        unbound_counts=unbound_counts,
    )


# ---------------------------------------------------------------- 방문 인스턴스
@researcher_bp.route("/<int:study_id>/subjects/<int:subject_id>/visits/<int:visit_id>/start", methods=["POST"])
@login_required
def start_visit(study_id, subject_id, visit_id):
    require_study_access(study_id)
    subject = db.get_or_404(Subject, subject_id)
    visit = db.get_or_404(Visit, visit_id)
    if visit.study_id != study_id or subject.study_id != study_id:
        abort(404)

    if not visit.allow_repeat:
        existing = VisitInstance.query.filter_by(subject_id=subject.id, visit_id=visit.id).first()
        if existing:
            return redirect(url_for("researcher.visit_instance_detail", study_id=study_id, subject_id=subject_id, vi_id=existing.id))

    form = VisitInstanceForm(request.form)
    vi = VisitInstance(
        subject_id=subject.id,
        visit_id=visit.id,
        instance_label=form.instance_label.data or None,
        visit_date=form.visit_date.data,
    )
    db.session.add(vi)
    AuditLog.record(current_user, study_id, "create", "VisitInstance", None, detail=f"{subject.subject_code} / {visit.name} 방문 시작", ip_address=request.remote_addr)
    db.session.commit()
    return redirect(url_for("researcher.visit_instance_detail", study_id=study_id, subject_id=subject_id, vi_id=vi.id))


@researcher_bp.route("/<int:study_id>/subjects/<int:subject_id>/visit_instances/<int:vi_id>")
@login_required
def visit_instance_detail(study_id, subject_id, vi_id):
    require_study_access(study_id)
    study = db.get_or_404(Study, study_id)
    subject = db.get_or_404(Subject, subject_id)
    vi = db.get_or_404(VisitInstance, vi_id)
    if vi.subject_id != subject_id or subject.study_id != study_id:
        abort(404)

    forms_here = FormTemplate.query.filter_by(study_id=study_id, visit_id=vi.visit_id).order_by(FormTemplate.order_index).all()
    form_status = []
    for ft in forms_here:
        records = ResponseRecord.query.filter_by(visit_instance_id=vi.id, form_id=ft.id).order_by(ResponseRecord.repeat_index).all()
        form_status.append({"form": ft, "records": records})

    return render_template("researcher/visit_instance_detail.html", study=study, subject=subject, vi=vi, form_status=form_status)


# ---------------------------------------------------------------- 응답 입력 (공통 로직)
def _branch_visible(field, raw_values):
    cond = field.get_branch_condition()
    if not cond:
        return True
    dep_val = raw_values.get(cond.get("field"), "")
    op = cond.get("op", "eq")
    target = cond.get("value", "")
    if op == "in":
        try:
            vals = json.loads(dep_val) if dep_val else []
        except (TypeError, ValueError):
            vals = [dep_val]
        return target in vals
    if op == "neq":
        return str(dep_val) != str(target)
    return str(dep_val) == str(target)


def _validate_required(fields, raw_values):
    errors = []
    for f in fields:
        if f.field_type in ("calculated", "section_header"):
            continue
        if not _branch_visible(f, raw_values):
            continue
        if f.required:
            val = raw_values.get(f.variable_name, "")
            if f.field_type == "checkbox":
                try:
                    vals = json.loads(val) if val else []
                except (TypeError, ValueError):
                    vals = []
                if not vals:
                    errors.append(f"'{f.label}' 항목은 필수 입력입니다.")
            elif not val:
                errors.append(f"'{f.label}' 항목은 필수 입력입니다.")
    return errors


def _collect_raw_values(fields):
    raw_values = {}
    for f in fields:
        if f.field_type in ("calculated", "section_header"):
            continue
        if f.field_type == "checkbox":
            vals = request.form.getlist(f.variable_name)
            raw_values[f.variable_name] = json.dumps(vals, ensure_ascii=False)
        else:
            raw_values[f.variable_name] = request.form.get(f.variable_name, "").strip()
    return raw_values


def _compute_calculated(fields, raw_values):
    calc_values = {}
    base_vars = dict(raw_values)
    for f in fields:
        if f.field_type == "calculated":
            try:
                result = evaluate_formula(f.calc_formula, {**base_vars, **calc_values})
                calc_values[f.variable_name] = round(result, 4) if isinstance(result, float) else result
            except FormulaError:
                calc_values[f.variable_name] = None
    return calc_values


def _render_and_save_record(study, subject, ft, record, vi, back_url):
    fields = ft.fields
    existing_values = record.value_map_by_variable() if record and record.id else {}
    posted_values = None

    if request.method == "POST":
        raw_values = _collect_raw_values(fields)
        errors = _validate_required(fields, raw_values)
        if errors:
            for e in errors:
                flash(e, "danger")
            posted_values = raw_values
        else:
            calc_values = _compute_calculated(fields, raw_values)
            is_new = record is None or record.id is None
            if record is None:
                record = ResponseRecord(subject_id=subject.id, form_id=ft.id, visit_instance_id=vi.id if vi else None)
                if ft.is_repeating:
                    max_idx = (
                        db.session.query(db.func.max(ResponseRecord.repeat_index))
                        .filter_by(subject_id=subject.id, form_id=ft.id, visit_instance_id=vi.id if vi else None)
                        .scalar()
                    )
                    # 주의: `scalar() or -1` 형태는 최댓값이 0일 때(첫 반복 항목) 0이 falsy로
                    # 취급되어 -1로 잘못 대체되는 버그가 있었음 (repeat_index가 계속 0으로 고정됨).
                    record.repeat_index = (max_idx + 1) if max_idx is not None else 0
                record.created_by_id = current_user.id
                db.session.add(record)
                db.session.flush()

            record.updated_by_id = current_user.id
            field_by_var = {f.variable_name: f for f in fields}
            existing_rv = {rv.field_id: rv for rv in record.values}
            all_values = dict(raw_values)
            all_values.update({k: ("" if v is None else str(v)) for k, v in calc_values.items()})
            for var, val in all_values.items():
                f = field_by_var.get(var)
                if f is None:
                    continue
                rv = existing_rv.get(f.id)
                if rv is None:
                    rv = ResponseValue(record_id=record.id, field_id=f.id)
                    db.session.add(rv)
                rv.value_text = val

            AuditLog.record(
                current_user,
                study.id,
                "create" if is_new else "update",
                "ResponseRecord",
                record.id,
                detail=f"{subject.subject_code} / {ft.name} 데이터 {'입력' if is_new else '수정'}",
                ip_address=request.remote_addr,
            )
            db.session.commit()
            flash("저장되었습니다.", "success")
            return redirect(back_url)

    display_values = posted_values if posted_values is not None else existing_values
    return render_template(
        "researcher/fill_form.html",
        study=study,
        subject=subject,
        ft=ft,
        fields=fields,
        values=display_values,
        record=record,
        back_url=back_url,
    )


# 방문에 종속된 비반복 폼: get-or-create 패턴
@researcher_bp.route("/<int:study_id>/subjects/<int:subject_id>/visit_instances/<int:vi_id>/forms/<int:form_id>", methods=["GET", "POST"])
@login_required
def fill_visit_form(study_id, subject_id, vi_id, form_id):
    require_study_access(study_id)
    study = db.get_or_404(Study, study_id)
    subject = db.get_or_404(Subject, subject_id)
    vi = db.get_or_404(VisitInstance, vi_id)
    ft = db.get_or_404(FormTemplate, form_id)
    if ft.is_repeating:
        return redirect(url_for("researcher.form_records", study_id=study_id, subject_id=subject_id, form_id=form_id, vi_id=vi_id))

    record = ResponseRecord.query.filter_by(subject_id=subject.id, visit_instance_id=vi.id, form_id=ft.id).first()
    back_url = url_for("researcher.visit_instance_detail", study_id=study_id, subject_id=subject_id, vi_id=vi_id)
    return _render_and_save_record(study, subject, ft, record, vi, back_url)


# 반복 입력 폼 (방문 종속 또는 비종속 공통): 목록 + 신규
@researcher_bp.route("/<int:study_id>/subjects/<int:subject_id>/forms/<int:form_id>/records", methods=["GET"])
@researcher_bp.route("/<int:study_id>/subjects/<int:subject_id>/visit_instances/<int:vi_id>/forms/<int:form_id>/records", methods=["GET"])
@login_required
def form_records(study_id, subject_id, form_id, vi_id=None):
    require_study_access(study_id)
    study = db.get_or_404(Study, study_id)
    subject = db.get_or_404(Subject, subject_id)
    ft = db.get_or_404(FormTemplate, form_id)
    vi = db.get_or_404(VisitInstance, vi_id) if vi_id else None

    query = ResponseRecord.query.filter_by(subject_id=subject.id, form_id=ft.id)
    query = query.filter_by(visit_instance_id=vi.id) if vi else query.filter_by(visit_instance_id=None)
    records = query.order_by(ResponseRecord.repeat_index).all()

    back_url = (
        url_for("researcher.visit_instance_detail", study_id=study_id, subject_id=subject_id, vi_id=vi.id)
        if vi
        else url_for("researcher.subject_detail", study_id=study_id, subject_id=subject_id)
    )
    return render_template("researcher/form_records.html", study=study, subject=subject, ft=ft, vi=vi, records=records, back_url=back_url)


@researcher_bp.route("/<int:study_id>/subjects/<int:subject_id>/forms/<int:form_id>/records/new", methods=["GET", "POST"])
@researcher_bp.route("/<int:study_id>/subjects/<int:subject_id>/visit_instances/<int:vi_id>/forms/<int:form_id>/records/new", methods=["GET", "POST"])
@login_required
def new_form_record(study_id, subject_id, form_id, vi_id=None):
    require_study_access(study_id)
    study = db.get_or_404(Study, study_id)
    subject = db.get_or_404(Subject, subject_id)
    ft = db.get_or_404(FormTemplate, form_id)
    vi = db.get_or_404(VisitInstance, vi_id) if vi_id else None

    back_url = url_for("researcher.form_records", study_id=study_id, subject_id=subject_id, form_id=form_id, vi_id=vi_id) if vi else url_for(
        "researcher.form_records", study_id=study_id, subject_id=subject_id, form_id=form_id
    )
    return _render_and_save_record(study, subject, ft, None, vi, back_url)


@researcher_bp.route("/<int:study_id>/subjects/<int:subject_id>/records/<int:record_id>/edit", methods=["GET", "POST"])
@login_required
def edit_form_record(study_id, subject_id, record_id):
    require_study_access(study_id)
    study = db.get_or_404(Study, study_id)
    subject = db.get_or_404(Subject, subject_id)
    record = db.get_or_404(ResponseRecord, record_id)
    if record.subject_id != subject_id:
        abort(404)
    ft = record.form
    vi = record.visit_instance

    if ft.is_repeating:
        back_url = (
            url_for("researcher.form_records", study_id=study_id, subject_id=subject_id, form_id=ft.id, vi_id=vi.id)
            if vi
            else url_for("researcher.form_records", study_id=study_id, subject_id=subject_id, form_id=ft.id)
        )
    else:
        back_url = (
            url_for("researcher.visit_instance_detail", study_id=study_id, subject_id=subject_id, vi_id=vi.id)
            if vi
            else url_for("researcher.subject_detail", study_id=study_id, subject_id=subject_id)
        )
    return _render_and_save_record(study, subject, ft, record, vi, back_url)


# ---------------------------------------------------------------- 데이터 내보내기 (CSV, 폼별로 zip)
@researcher_bp.route("/<int:study_id>/export")
@login_required
def export_study(study_id):
    require_study_access(study_id)
    study = db.get_or_404(Study, study_id)

    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        forms = FormTemplate.query.filter_by(study_id=study.id).order_by(FormTemplate.order_index).all()
        for ft in forms:
            records = ResponseRecord.query.filter_by(form_id=ft.id).order_by(ResponseRecord.id).all()
            fields = ft.fields
            header = ["subject_code", "visit_name", "visit_instance_label", "visit_date", "repeat_index"] + [f.variable_name for f in fields]
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(header)
            for rec in records:
                vmap = rec.value_map_by_variable()
                row = [
                    rec.subject.subject_code,
                    rec.visit_instance.visit.name if rec.visit_instance else "",
                    rec.visit_instance.instance_label if rec.visit_instance else "",
                    rec.visit_instance.visit_date.isoformat() if (rec.visit_instance and rec.visit_instance.visit_date) else "",
                    rec.repeat_index,
                ]
                for f in fields:
                    row.append(vmap.get(f.variable_name, ""))
                writer.writerow(row)
            safe_name = "".join(c for c in ft.name if c.isalnum() or c in ("_", "-")) or f"form_{ft.id}"
            zf.writestr(f"{safe_name}.csv", "﻿" + buf.getvalue())

    mem_zip.seek(0)
    AuditLog.record(current_user, study.id, "export", "Study", study.id, detail=f"{study.name} 데이터 내보내기", ip_address=request.remote_addr)
    db.session.commit()
    filename = f"{study.code}_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.zip"
    return send_file(mem_zip, mimetype="application/zip", as_attachment=True, download_name=filename)
