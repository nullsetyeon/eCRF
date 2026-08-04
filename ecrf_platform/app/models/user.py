from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_platform_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_active_flag = db.Column("is_active", db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)

    memberships = db.relationship("StudyMembership", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    @property
    def is_active(self):
        return self.is_active_flag

    def role_for_study(self, study_id):
        for m in self.memberships:
            if m.study_id == study_id:
                return m.role
        return None

    def can_manage_study(self, study_id):
        if self.is_platform_admin:
            return True
        return self.role_for_study(study_id) == "study_admin"

    def can_access_study(self, study_id):
        if self.is_platform_admin:
            return True
        return self.role_for_study(study_id) is not None

    def __repr__(self):
        return f"<User {self.email}>"
