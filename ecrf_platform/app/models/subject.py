from datetime import datetime, timezone
from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class Subject(db.Model):
    """연구 대상자 (등록번호로만 식별 - 실명 등 직접식별정보는 저장하지 않는 것을 권장)."""

    __tablename__ = "subjects"
    __table_args__ = (db.UniqueConstraint("study_id", "subject_code", name="uq_study_subject_code"),)

    id = db.Column(db.Integer, primary_key=True)
    study_id = db.Column(db.Integer, db.ForeignKey("studies.id"), nullable=False)
    subject_code = db.Column(db.String(64), nullable=False)  # 예: HP-001
    status = db.Column(db.String(32), default="등록", nullable=False)
    memo = db.Column(db.Text, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    study = db.relationship("Study", back_populates="subjects")
    created_by = db.relationship("User")
    visit_instances = db.relationship("VisitInstance", back_populates="subject", cascade="all, delete-orphan")


class VisitInstance(db.Model):
    """대상자별 실제 방문 1회 (allow_repeat 방문은 여러 인스턴스 가능 - 예: 예정외방문 1차, 2차)."""

    __tablename__ = "visit_instances"

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=False)
    instance_label = db.Column(db.String(120), nullable=True)  # 반복방문 구분용 (예: "1차")
    visit_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    subject = db.relationship("Subject", back_populates="visit_instances")
    visit = db.relationship("Visit")
    response_records = db.relationship(
        "ResponseRecord", back_populates="visit_instance", cascade="all, delete-orphan"
    )


class ResponseRecord(db.Model):
    """대상자 + 방문 + 폼에 대한 1회 제출 (반복 입력폼은 같은 조합으로 여러 레코드 가능)."""

    __tablename__ = "response_records"

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False)
    visit_instance_id = db.Column(db.Integer, db.ForeignKey("visit_instances.id"), nullable=True)
    form_id = db.Column(db.Integer, db.ForeignKey("form_templates.id"), nullable=False)
    repeat_index = db.Column(db.Integer, default=0, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    subject = db.relationship("Subject")
    visit_instance = db.relationship("VisitInstance", back_populates="response_records")
    form = db.relationship("FormTemplate")
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    updated_by = db.relationship("User", foreign_keys=[updated_by_id])
    values = db.relationship("ResponseValue", back_populates="record", cascade="all, delete-orphan")

    def value_map(self):
        return {v.field_id: v.value_text for v in self.values}

    def value_map_by_variable(self):
        return {v.field.variable_name: v.value_text for v in self.values}


class ResponseValue(db.Model):
    """개별 문항 응답값 (단순화를 위해 텍스트로 저장, 체크박스 다중값은 JSON 문자열)."""

    __tablename__ = "response_values"
    __table_args__ = (db.UniqueConstraint("record_id", "field_id", name="uq_record_field"),)

    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(db.Integer, db.ForeignKey("response_records.id"), nullable=False)
    field_id = db.Column(db.Integer, db.ForeignKey("fields.id"), nullable=False)
    value_text = db.Column(db.Text, nullable=True)

    record = db.relationship("ResponseRecord", back_populates="values")
    field = db.relationship("Field")
