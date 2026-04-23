import os
from flask import Flask, request
from flask_cors import CORS

# 允许访问的前端 origin 白名单；带 * 作兜底（开发期），部署正式可收紧。
ALLOWED_ORIGINS = {
    'http://localhost:5173',
    'http://localhost:5174',
    'https://compensation-diagnostic-frontend.onrender.com',
}

def create_app():
    app = Flask(__name__)
    app.config.from_object('app.config.Config')

    # flask-cors 管正常响应的 CORS 头
    CORS(app, resources={r'/api/*': {'origins': list(ALLOWED_ORIGINS)}},
         supports_credentials=False, max_age=3600)

    # 兜底：Werkzeug 在异常/500 等场景可能绕过 flask-cors 中间件，
    # 用 after_request 手动保证所有响应都带 CORS 头，否则浏览器会误报
    # "No Access-Control-Allow-Origin header"，掩盖真正的后端错误
    @app.after_request
    def ensure_cors_headers(response):
        origin = request.headers.get('Origin')
        if origin and origin in ALLOWED_ORIGINS:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response.headers['Vary'] = 'Origin'
        return response

    # session 写回合并：每个请求结束统一 flush 一次脏 session，
    # 避免 analyze 这种多次 setitem 的接口把整份 session 反复序列化、撑爆 512MB
    @app.after_request
    def flush_dirty_sessions(response):
        try:
            from app.api.sessions import sessions_store
            sessions_store.flush_all_dirty()
        except Exception as e:
            print(f'[after_request] session flush failed: {e}')
        return response

    # 启动时初始化 DB（create_all，幂等）
    try:
        from app.core.db import init_db
        init_db()
    except Exception as e:
        print(f'[startup] db init failed: {e}')

    # Register blueprints
    from app.api.auth import auth_bp
    from app.api.sessions import sessions_bp
    from app.api.upload import upload_bp
    from app.api.chat import chat_bp
    from app.api.report import report_bp
    from app.api.pipeline_steps import pipeline_bp
    from app.api.skill import skill_bp

    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(sessions_bp, url_prefix='/api/sessions')
    app.register_blueprint(upload_bp, url_prefix='/api/upload')
    app.register_blueprint(chat_bp, url_prefix='/api/chat')
    app.register_blueprint(report_bp, url_prefix='/api/report')
    app.register_blueprint(pipeline_bp, url_prefix='/api/pipeline')
    app.register_blueprint(skill_bp, url_prefix='/api/skill')

    @app.route('/api/health')
    def health():
        return {'status': 'ok'}

    # 启动时预热市场薪酬数据缓存 —— 把成本从 /analyze 的请求路径挪到 worker boot
    # 即使加载慢也只影响 boot，不会触发 gunicorn 30s 请求超时
    try:
        from app.services.market_data import get_market_data
        get_market_data()
    except Exception as e:
        print(f'[startup] market_data preload failed: {e}')

    return app

app = create_app()
