"""Flask-WTF 폼 정의 (CSRF 보호가 자동 적용됨)."""

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, TextAreaField, BooleanField, DateField
from wtforms.validators import DataRequired, Email, Length, Optional


class LoginForm(FlaskForm):
    email = StringField("이메일", validators=[DataRequired(), Email()])
    password = PasswordField("비밀번호", validators=[DataRequired()])


class StudyForm(FlaskForm):
    name = StringField("연구명", validators=[DataRequired(), Length(max=255)])
    code = StringField("연구 코드 (영문/숫자, 고유값)", validators=[DataRequired(), Length(max=64)])
    description = TextAreaField("설명", validators=[Optional()])


class InviteMemberForm(FlaskForm):
    name = StringField("이름", validators=[DataRequired(), Length(max=120)])
    email = StringField("이메일", validators=[DataRequired(), Email()])
    role = SelectField("권한", choices=[])
    temp_password = StringField("임시 비밀번호 (신규 계정인 경우)", validators=[Optional(), Length(min=8)])


class VisitForm(FlaskForm):
    name = StringField("방문명 (예: V1 스크리닝)", validators=[DataRequired(), Length(max=120)])
    window_description = StringField("방문 시기 설명 (예: 0주)", validators=[Optional(), Length(max=255)])
    allow_repeat = BooleanField("반복 방문 허용 (예정외방문 등)")


class FormTemplateForm(FlaskForm):
    name = StringField("폼 이름", validators=[DataRequired(), Length(max=200)])
    visit_id = SelectField("연결할 방문 (반복기록폼은 '방문 비종속' 선택)", coerce=int)
    is_repeating = BooleanField("반복 입력 폼 (예: 이상반응 로그처럼 여러 건 기록)")


class SubjectForm(FlaskForm):
    subject_code = StringField("대상자 등록번호 (예: HP-001)", validators=[DataRequired(), Length(max=64)])
    memo = TextAreaField("메모", validators=[Optional()])


class VisitInstanceForm(FlaskForm):
    instance_label = StringField("회차 구분 (예: 1차)", validators=[Optional(), Length(max=120)])
    visit_date = DateField("방문일", validators=[Optional()])
