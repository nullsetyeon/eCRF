"""전체 흐름 스모크 테스트: 연구 생성 -> 방문/폼/필드(분기+계산 포함) 설계
-> 연구원 초대 -> 대상자 등록 -> 데이터 입력 -> 계산필드 검증 -> CSV 내보내기 검증.

실행: python3 smoke_test.py
"""
import os
import re
import sys
import zipfile
import io

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret"

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from app.extensions import db
from app.models.user import User

app = create_app()
app.config["WTF_CSRF_ENABLED"] = True  # CSRF까지 포함해서 실제 운영과 동일하게 검증
app.config["TESTING"] = True

CSRF_RE = re.compile(r'<input[^>]*name="csrf_token"[^>]*>')
VALUE_RE = re.compile(r'value="([^"]*)"')


def get_csrf(html):
    m = CSRF_RE.search(html)
    assert m, "CSRF 토큰을 찾을 수 없습니다.\n" + html[:500]
    vm = VALUE_RE.search(m.group(0))
    assert vm, "CSRF input에서 value를 찾을 수 없습니다: " + m.group(0)
    return vm.group(1)


def check(condition, msg):
    if not condition:
        raise AssertionError("FAIL: " + msg)
    print("OK  -", msg)


with app.app_context():
    db.drop_all()
    db.create_all()
    admin = User(name="조나현", email="admin@example.com", is_platform_admin=True)
    admin.set_password("adminpass123")
    researcher = User(name="김연구", email="researcher@example.com", is_platform_admin=False)
    researcher.set_password("respass123")
    db.session.add_all([admin, researcher])
    db.session.commit()

client = app.test_client()

# 1. 관리자 로그인
r = client.get("/login")
token = get_csrf(r.get_data(as_text=True))
r = client.post("/login", data={"csrf_token": token, "email": "admin@example.com", "password": "adminpass123"}, follow_redirects=True)
check(r.status_code == 200 and "로그아웃" in r.get_data(as_text=True), "관리자 로그인 성공")

# 2. 연구 생성
r = client.get("/admin/studies")
token = get_csrf(r.get_data(as_text=True))
r = client.post(
    "/admin/studies",
    data={"csrf_token": token, "name": "고혈압 생맥산가감방 연구", "code": "HP2026", "description": "테스트"},
    follow_redirects=True,
)
check(r.status_code == 200, "연구 생성 성공")
with app.app_context():
    from app.models.study import Study

    study = Study.query.filter_by(code="HP2026").first()
    check(study is not None, "DB에 연구가 저장됨")
    study_id = study.id

# 3. 연구원 초대
r = client.get(f"/admin/studies/{study_id}/members")
token = get_csrf(r.get_data(as_text=True))
r = client.post(
    f"/admin/studies/{study_id}/members",
    data={"csrf_token": token, "name": "김연구", "email": "researcher@example.com", "role": "researcher", "temp_password": ""},
    follow_redirects=True,
)
check(r.status_code == 200, "연구원 초대 성공")

# 4. 방문 추가 (V1)
r = client.get(f"/admin/studies/{study_id}/visits")
token = get_csrf(r.get_data(as_text=True))
r = client.post(
    f"/admin/studies/{study_id}/visits",
    data={"csrf_token": token, "name": "V1 스크리닝", "window_description": "0주", "allow_repeat": ""},
    follow_redirects=True,
)
check(r.status_code == 200, "방문(V1) 추가 성공")

with app.app_context():
    from app.models.form import Visit, FormTemplate, Field

    visit1 = Visit.query.filter_by(study_id=study_id, name="V1 스크리닝").first()
    check(visit1 is not None, "DB에 방문 저장됨")
    visit1_id = visit1.id

# 5. 폼 추가 (활력징후)
r = client.get(f"/admin/studies/{study_id}/forms")
token = get_csrf(r.get_data(as_text=True))
r = client.post(
    f"/admin/studies/{study_id}/forms",
    data={"csrf_token": token, "name": "활력징후", "visit_id": str(visit1_id), "is_repeating": ""},
    follow_redirects=True,
)
check(r.status_code == 200, "폼(활력징후) 추가 성공")

with app.app_context():
    ft = FormTemplate.query.filter_by(study_id=study_id, name="활력징후").first()
    check(ft is not None, "DB에 폼 저장됨")
    form_id = ft.id

# 6. 필드 추가: height(숫자), weight(숫자), bmi(계산), smoker(라디오), smoke_years(분기 조건부 숫자)
def add_field(**kwargs):
    r = client.get(f"/admin/forms/{form_id}/builder")
    token = get_csrf(r.get_data(as_text=True))
    payload = {"csrf_token": token, "help_text": "", "unit": "", "options_text": "", "calc_formula": "", "branch_field": "", "branch_op": "eq", "branch_value": ""}
    payload.update(kwargs)
    r = client.post(f"/admin/forms/{form_id}/fields/new", data=payload, follow_redirects=True)
    return r

add_field(variable_name="height", label="신장", field_type="number", unit="cm", required="on")
add_field(variable_name="weight", label="체중", field_type="number", unit="kg", required="on")
add_field(
    variable_name="bmi",
    label="BMI (자동계산)",
    field_type="calculated",
    calc_formula="round(weight / ((height/100) ** 2), 1)",
)
add_field(
    variable_name="smoker",
    label="흡연 여부",
    field_type="radio",
    options_text="Y|예\nN|아니오",
    required="on",
)
add_field(
    variable_name="smoke_years",
    label="흡연 기간(년)",
    field_type="number",
    branch_field="smoker",
    branch_op="eq",
    branch_value="Y",
)

with app.app_context():
    ft = db.session.get(FormTemplate, form_id)
    var_names = [f.variable_name for f in ft.fields]
    check(var_names == ["height", "weight", "bmi", "smoker", "smoke_years"], f"5개 필드 순서대로 저장됨: {var_names}")
    bmi_field = ft.field_by_variable("bmi")
    check(bmi_field.field_type == "calculated" and bmi_field.calc_formula, "계산필드(BMI) 저장됨")
    smoke_years_field = ft.field_by_variable("smoke_years")
    cond = smoke_years_field.get_branch_condition()
    check(cond == {"field": "smoker", "op": "eq", "value": "Y"}, "분기로직(흡연기간) 저장됨")

# 7. 로그아웃 후 연구원으로 로그인
client.get("/logout")
r = client.get("/login")
token = get_csrf(r.get_data(as_text=True))
r = client.post("/login", data={"csrf_token": token, "email": "researcher@example.com", "password": "respass123"}, follow_redirects=True)
check("로그아웃" in r.get_data(as_text=True), "연구원 로그인 성공")

# 연구원이 관리자 페이지 접근 시 403이어야 함 (권한 분리 검증)
r = client.get(f"/admin/studies/{study_id}/visits")
check(r.status_code == 403, "연구원은 폼 설계 페이지 접근 불가 (403)")

# 8. 대상자 등록
r = client.get(f"/studies/{study_id}/subjects")
token = get_csrf(r.get_data(as_text=True))
r = client.post(f"/studies/{study_id}/subjects", data={"csrf_token": token, "subject_code": "HP-001", "memo": ""}, follow_redirects=True)
check("HP-001" in r.get_data(as_text=True), "대상자(HP-001) 등록 성공")

with app.app_context():
    from app.models.subject import Subject

    subject = Subject.query.filter_by(study_id=study_id, subject_code="HP-001").first()
    subject_id = subject.id

# 9. 방문 시작 (V1)
r = client.get(f"/studies/{study_id}/subjects/{subject_id}")
token = get_csrf(r.get_data(as_text=True))
r = client.post(
    f"/studies/{study_id}/subjects/{subject_id}/visits/{visit1_id}/start",
    data={"csrf_token": token, "instance_label": "", "visit_date": ""},
    follow_redirects=True,
)
check(r.status_code == 200, "V1 방문 시작 성공")

with app.app_context():
    from app.models.subject import VisitInstance

    vi = VisitInstance.query.filter_by(subject_id=subject_id, visit_id=visit1_id).first()
    check(vi is not None, "방문 인스턴스 생성됨")
    vi_id = vi.id

# 10. 데이터 입력 (분기: 흡연=예 -> smoke_years 노출/저장, BMI 자동계산 검증)
r = client.get(f"/studies/{study_id}/subjects/{subject_id}/visit_instances/{vi_id}/forms/{form_id}")
token = get_csrf(r.get_data(as_text=True))
r = client.post(
    f"/studies/{study_id}/subjects/{subject_id}/visit_instances/{vi_id}/forms/{form_id}",
    data={"csrf_token": token, "height": "170", "weight": "65", "smoker": "Y", "smoke_years": "10"},
    follow_redirects=True,
)
check(r.status_code == 200 and ("저장되었습니다" in r.get_data(as_text=True) or "입력 완료" in r.get_data(as_text=True)), "활력징후 데이터 저장 성공")

with app.app_context():
    from app.models.subject import ResponseRecord

    rec = ResponseRecord.query.filter_by(subject_id=subject_id, visit_instance_id=vi_id, form_id=form_id).first()
    check(rec is not None, "응답 레코드 생성됨")
    vmap = rec.value_map_by_variable()
    check(vmap.get("height") == "170" and vmap.get("weight") == "65", "원본 값 저장 확인")
    expected_bmi = round(65 / ((170 / 100) ** 2), 1)
    check(vmap.get("bmi") == str(expected_bmi), f"BMI 자동계산 정확성 확인 (기대값 {expected_bmi}, 실제 {vmap.get('bmi')})")
    check(vmap.get("smoke_years") == "10", "분기로직으로 노출된 필드 값 저장 확인")

# 11. 필수값 누락 시 검증 오류가 발생하는지 확인 (weight 비움)
r = client.get(f"/studies/{study_id}/subjects/{subject_id}/visit_instances/{vi_id}/forms/{form_id}")
token = get_csrf(r.get_data(as_text=True))
r = client.post(
    f"/studies/{study_id}/subjects/{subject_id}/visit_instances/{vi_id}/forms/{form_id}",
    data={"csrf_token": token, "height": "170", "weight": "", "smoker": "Y", "smoke_years": "10"},
    follow_redirects=True,
)
check("필수 입력" in r.get_data(as_text=True), "필수값 누락 시 검증 오류 메시지 노출")

# 11-b. 관리자로 다시 전환 -> 반복입력 폼(이상반응 로그, 방문 비종속) 생성 + 필드 순서 변경 검증
client.get("/logout")
r = client.get("/login")
token = get_csrf(r.get_data(as_text=True))
client.post("/login", data={"csrf_token": token, "email": "admin@example.com", "password": "adminpass123"}, follow_redirects=True)

r = client.get(f"/admin/studies/{study_id}/forms")
token = get_csrf(r.get_data(as_text=True))
r = client.post(
    f"/admin/studies/{study_id}/forms",
    data={"csrf_token": token, "name": "이상반응 로그", "visit_id": "0", "is_repeating": "on"},
    follow_redirects=True,
)
check(r.status_code == 200, "반복입력 폼(이상반응 로그) 추가 성공")

with app.app_context():
    ae_form = FormTemplate.query.filter_by(study_id=study_id, name="이상반응 로그").first()
    ae_form_id = ae_form.id

def add_ae_field(**kwargs):
    r = client.get(f"/admin/forms/{ae_form_id}/builder")
    token = get_csrf(r.get_data(as_text=True))
    payload = {"csrf_token": token, "help_text": "", "unit": "", "options_text": "", "calc_formula": "", "branch_field": "", "branch_op": "eq", "branch_value": ""}
    payload.update(kwargs)
    return client.post(f"/admin/forms/{ae_form_id}/fields/new", data=payload, follow_redirects=True)

add_ae_field(variable_name="ae_term", label="이상반응명", field_type="text", required="on")
add_ae_field(variable_name="ae_severity", label="중증도", field_type="radio", options_text="mild|경증\nmoderate|중등도\nsevere|중증")

with app.app_context():
    ae_form = db.session.get(FormTemplate, ae_form_id)
    check([f.variable_name for f in ae_form.fields] == ["ae_term", "ae_severity"], "이상반응 로그 필드 2개 저장됨")
    field_ids = [f.id for f in ae_form.fields]

# 필드 순서 뒤집기 (드래그앤드롭 reorder AJAX 엔드포인트 검증) - 실제 JS와 동일하게 CSRF 헤더 포함
r = client.get(f"/admin/forms/{ae_form_id}/builder")
token = get_csrf(r.get_data(as_text=True))
r = client.post(
    f"/admin/forms/{ae_form_id}/fields/reorder",
    json={"field_ids": list(reversed(field_ids))},
    headers={"X-CSRFToken": token},
)
check(r.status_code == 200 and r.get_json().get("ok") is True, "필드 순서변경(reorder) API 정상 응답")
with app.app_context():
    ae_form = db.session.get(FormTemplate, ae_form_id)
    check([f.variable_name for f in ae_form.fields] == ["ae_severity", "ae_term"], "필드 순서가 실제로 뒤바뀜")

# 11-c. 연구원으로 전환 -> 반복입력 폼에 2건 기록
client.get("/logout")
r = client.get("/login")
token = get_csrf(r.get_data(as_text=True))
client.post("/login", data={"csrf_token": token, "email": "researcher@example.com", "password": "respass123"}, follow_redirects=True)

for term, sev in [("두드러기", "mild"), ("어지러움", "moderate")]:
    r = client.get(f"/studies/{study_id}/subjects/{subject_id}/forms/{ae_form_id}/records/new")
    token = get_csrf(r.get_data(as_text=True))
    r = client.post(
        f"/studies/{study_id}/subjects/{subject_id}/forms/{ae_form_id}/records/new",
        data={"csrf_token": token, "ae_term": term, "ae_severity": sev},
        follow_redirects=True,
    )
    check(r.status_code == 200, f"이상반응 기록 추가 성공: {term}")

with app.app_context():
    ae_records = ResponseRecord.query.filter_by(subject_id=subject_id, form_id=ae_form_id).order_by(ResponseRecord.repeat_index).all()
    check(len(ae_records) == 2, f"반복입력 폼 레코드 2건 생성 확인 (실제 {len(ae_records)}건)")
    check([r.repeat_index for r in ae_records] == [0, 1], "반복입력 repeat_index 0,1로 순차 부여됨")
    check(ae_records[0].value_map_by_variable().get("ae_term") == "두드러기", "1번째 기록 내용 확인")
    check(ae_records[1].value_map_by_variable().get("ae_term") == "어지러움", "2번째 기록 내용 확인")

r = client.get(f"/studies/{study_id}/subjects/{subject_id}/forms/{ae_form_id}/records")
check(r.status_code == 200, "이상반응 기록 목록 화면 정상 응답")

# 12. CSV(zip) 내보내기 확인
r = client.get(f"/studies/{study_id}/export")
check(r.status_code == 200 and r.mimetype == "application/zip", "CSV(zip) 내보내기 응답 정상")
zf = zipfile.ZipFile(io.BytesIO(r.data))
names = zf.namelist()
check(len(names) == 2 and all(n.endswith(".csv") for n in names), f"zip 안에 폼별 CSV 2개 포함 확인: {names}")
vitals_csv = zf.read("활력징후.csv").decode("utf-8-sig")
check("HP-001" in vitals_csv and str(expected_bmi) in vitals_csv, "활력징후 CSV 내용에 대상자/BMI 값 포함 확인")
ae_csv = zf.read("이상반응로그.csv").decode("utf-8-sig")
check("두드러기" in ae_csv and "어지러움" in ae_csv, "이상반응 로그 CSV에 2건 모두 포함 확인")

# 13. 감사로그(Audit) 기록 확인
with app.app_context():
    from app.models.audit import AuditLog

    count = AuditLog.query.count()
    check(count > 5, f"감사로그(Audit trail) {count}건 기록됨")
    login_logs = AuditLog.query.filter_by(action="login").count()
    check(login_logs >= 2, "로그인 이벤트 감사로그 기록 확인")

print("\n=== 전체 스모크 테스트 통과 ===")
