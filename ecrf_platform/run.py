from dotenv import load_dotenv

load_dotenv()  # .env 파일이 있으면 환경변수로 읽어옵니다.

from app import create_app

app = create_app()

if __name__ == "__main__":
    # 로컬 개발/검증용 실행. 운영 배포 시에는 gunicorn 등 WSGI 서버를 사용하세요 (README 참고).
    app.run(host="0.0.0.0", port=5000, debug=True)
