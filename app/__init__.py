import os
from flask import Flask
from flask_cors import CORS

def create_app():
    app = Flask(__name__)
    app.config.from_object('app.config.Config')

    CORS(app, origins=[
        'http://localhost:5173',
        'https://compensation-diagnostic-frontend.onrender.com',
    ])

    # Register blueprints
    from app.api.sessions import sessions_bp
    from app.api.upload import upload_bp
    from app.api.chat import chat_bp
    from app.api.report import report_bp
    from app.api.pipeline_steps import pipeline_bp

    app.register_blueprint(sessions_bp, url_prefix='/api/sessions')
    app.register_blueprint(upload_bp, url_prefix='/api/upload')
    app.register_blueprint(chat_bp, url_prefix='/api/chat')
    app.register_blueprint(report_bp, url_prefix='/api/report')
    app.register_blueprint(pipeline_bp, url_prefix='/api/pipeline')

    @app.route('/api/health')
    def health():
        return {'status': 'ok'}

    return app

app = create_app()
