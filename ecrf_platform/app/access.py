from functools import wraps
from flask import abort
from flask_login import current_user


def platform_admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_platform_admin:
            abort(403)
        return fn(*args, **kwargs)

    return wrapper


def require_study_admin(study_id):
    if not current_user.is_authenticated or not current_user.can_manage_study(study_id):
        abort(403)


def require_study_access(study_id):
    if not current_user.is_authenticated or not current_user.can_access_study(study_id):
        abort(403)
