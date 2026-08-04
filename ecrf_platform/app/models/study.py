from datetime import datetime, timezone
from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class Study(db.Model):
    __tablename__ = "studies"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    code = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    created_by = db.relationship("User", foreign_keys=[created_by_id])
    memberships = db.relationship("StudyMembership", back_populates="study", cascade="all, delete-orphan")
    visits = db.relationship(
        "Visit", back_populates="study", cascade="all, delete-orphan", order_by="Visit.order_index"
    )
    subjects = db.relationship("Subject", back_populates="study", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Study {self.code}>"


ROLE_STUDY_ADMIN = "study_admin"
ROLE_RESEARCHER = "researcher"
ROLE_CHOICES = [
    (ROLE_STUDY_ADMIN, "연구 관리자 (폼 설계·연구원 초대 가능)"),
    (ROLE_RESEARCHER, "연구원 (데이터 입력/조회만 가능)"),
]


class StudyMembership(db.Model):
    __tablename__ = "study_memberships"
    __table_args__ = (db.UniqueConstraint("study_id", "user_id", name="uq_study_user"),)

    id = db.Column(db.Integer, primary_key=True)
    study_id = db.Column(db.Integer, db.ForeignKey("studies.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    role = db.Column(db.String(32), nullable=False, default=ROLE_RESEARCHER)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    study = db.relationship("Study", back_populates="memberships")
    user = db.relationship("User", back_populates="memberships")
