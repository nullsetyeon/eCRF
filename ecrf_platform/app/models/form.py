import json
from datetime import datetime, timezone
from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class Visit(db.Model):
    """연구의 방문 스케줄 (예: V1 스크리닝, V2 4주, V3 8주...)."""

    __tablename__ = "visits"

    id = db.Column(db.Integer, primary_key=True)
    study_id = db.Column(db.Integer, db.ForeignKey("studies.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    window_description = db.Column(db.String(255), nullable=True)  # 예: "0주 (스크리닝/등록)"
    allow_repeat = db.Column(db.Boolean, default=False, nullable=False)  # 예정외방문처럼 반복 가능한지
    order_index = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    study = db.relationship("Study", back_populates="visits")
    forms = db.relationship(
        "FormTemplate", back_populates="visit", cascade="all, delete-orphan", order_by="FormTemplate.order_index"
    )


FIELD_TYPES = [
    ("text", "단답형 텍스트"),
    ("textarea", "장문형 텍스트"),
    ("number", "숫자"),
    ("date", "날짜"),
    ("radio", "단일 선택 (라디오버튼)"),
    ("select", "단일 선택 (드롭다운)"),
    ("checkbox", "다중 선택 (체크박스)"),
    ("calculated", "자동 계산 필드"),
    ("section_header", "구분선/섹션 제목 (입력값 없음)"),
]

FIELD_TYPES_WITH_OPTIONS = {"radio", "select", "checkbox"}


class FormTemplate(db.Model):
    """하나의 CRF 폼 (예: 활력징후, 이상반응 로그 등)."""

    __tablename__ = "form_templates"

    id = db.Column(db.Integer, primary_key=True)
    study_id = db.Column(db.Integer, db.ForeignKey("studies.id"), nullable=False)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True)  # null이면 방문 비종속(반복기록폼)
    name = db.Column(db.String(200), nullable=False)
    is_repeating = db.Column(db.Boolean, default=False, nullable=False)  # 이상반응 로그처럼 여러 건 반복 입력
    order_index = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    study = db.relationship("Study")
    visit = db.relationship("Visit", back_populates="forms")
    fields = db.relationship(
        "Field", back_populates="form", cascade="all, delete-orphan", order_by="Field.order_index"
    )

    def field_by_variable(self, variable_name):
        for f in self.fields:
            if f.variable_name == variable_name:
                return f
        return None


class Field(db.Model):
    """폼 안의 개별 문항."""

    __tablename__ = "fields"
    __table_args__ = (db.UniqueConstraint("form_id", "variable_name", name="uq_form_variable"),)

    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey("form_templates.id"), nullable=False)
    variable_name = db.Column(db.String(80), nullable=False)  # 계산식/분기로직에서 참조하는 코드명
    label = db.Column(db.String(500), nullable=False)
    help_text = db.Column(db.String(500), nullable=True)
    field_type = db.Column(db.String(32), nullable=False, default="text")
    options_json = db.Column(db.Text, nullable=True)  # [{"value": "1", "label": "예"}, ...]
    unit = db.Column(db.String(40), nullable=True)
    required = db.Column(db.Boolean, default=False, nullable=False)
    order_index = db.Column(db.Integer, default=0, nullable=False)

    # 분기로직: {"field": "다른변수명", "op": "eq|neq|in", "value": "..."}
    branch_condition_json = db.Column(db.Text, nullable=True)
    # 계산필드 수식: 같은 폼 안의 다른 variable_name들을 사용한 파이썬 산술식
    # 예: "round(weight / ((height/100) ** 2), 1)"
    calc_formula = db.Column(db.String(500), nullable=True)

    form = db.relationship("FormTemplate", back_populates="fields")

    def get_options(self):
        if not self.options_json:
            return []
        return json.loads(self.options_json)

    def set_options(self, options):
        self.options_json = json.dumps(options, ensure_ascii=False)

    def get_branch_condition(self):
        if not self.branch_condition_json:
            return None
        return json.loads(self.branch_condition_json)

    def set_branch_condition(self, cond):
        self.branch_condition_json = json.dumps(cond, ensure_ascii=False) if cond else None
