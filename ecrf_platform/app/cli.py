import click
from app.extensions import db


def register(app):
    @app.cli.command("init-db")
    def init_db():
        """데이터베이스 테이블을 생성합니다."""
        db.create_all()
        click.echo("데이터베이스 테이블 생성 완료.")

    @app.cli.command("create-admin")
    @click.option("--name", prompt="이름")
    @click.option("--email", prompt="이메일")
    @click.option("--password", prompt="비밀번호", hide_input=True, confirmation_prompt=True)
    def create_admin(name, email, password):
        """플랫폼 관리자 계정을 생성합니다."""
        from app.models.user import User

        db.create_all()
        existing = User.query.filter_by(email=email).first()
        if existing:
            click.echo("이미 존재하는 이메일입니다.")
            return
        user = User(name=name, email=email, is_platform_admin=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"플랫폼 관리자 계정 생성 완료: {email}")
