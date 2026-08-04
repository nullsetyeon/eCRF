import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # SECRET_KEY는 배포 시 반드시 환경변수로 재설정해야 합니다.
    # (개발용 기본값이 그대로 운영 서버에 남아있으면 세션 위조가 가능해집니다.)
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

    _db_url = os.environ.get("DATABASE_URL", "").strip()
    if _db_url.startswith("postgres://"):
        # Render/Heroku 등에서 내려주는 postgres:// 스킴을 SQLAlchemy가 요구하는
        # postgresql:// 로 보정합니다.
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url or f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'ecrf.db')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # 세션 보안 / 자동 로그아웃
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # 운영(HTTPS) 배포 시 반드시 True로 설정 (환경변수 SESSION_COOKIE_SECURE=1)
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"

    WTF_CSRF_ENABLED = True

    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 업로드 파일 5MB 제한
