from datetime import datetime, timezone
from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class AuditLog(db.Model):
    """감사추적: 구조 변경(폼/필드) 및 데이터 변경(대상자/응답)을 모두 기록."""

    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    study_id = db.Column(db.Integer, db.ForeignKey("studies.id"), nullable=True)
    action = db.Column(db.String(32), nullable=False)  # create/update/delete/login/export ...
    entity_type = db.Column(db.String(64), nullable=False)  # Study/Visit/FormTemplate/Field/Subject/ResponseRecord
    entity_id = db.Column(db.Integer, nullable=True)
    detail = db.Column(db.Text, nullable=True)  # 사람이 읽을 수 있는 변경 요약
    ip_address = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, index=True)

    user = db.relationship("User")
    study = db.relationship("Study")

    @staticmethod
    def record(user, study_id, action, entity_type, entity_id, detail=None, ip_address=None):
        entry = AuditLog(
            user_id=user.id if user and user.is_authenticated else None,
            study_id=study_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail,
            ip_address=ip_address,
        )
        db.session.add(entry)
        return entry
