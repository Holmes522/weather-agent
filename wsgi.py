"""生产 WSGI 入口，由 Gunicorn 导入。"""

from app import create_app


app = create_app()
