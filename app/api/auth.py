"""
Auth endpoints: register / login / me

POST /api/auth/register  {email, password, display_name?, company_name?}
  → {token, user: {id, email, display_name}, workspace: {id, name}}
  - 同 email 已存在 → 409
  - 自动创建一个 workspace 挂上去

POST /api/auth/login  {email, password}
  → {token, user, workspace}
  - 失败 → 401

GET /api/auth/me  (Authorization: Bearer)
  → {user, workspace}
  - 未登录 → 401
"""
from flask import Blueprint, request, jsonify, g
from app.core.db import SessionLocal
from app.core.models import User, Workspace
from app.core.auth import hash_password, verify_password, issue_token, require_auth

auth_bp = Blueprint('auth', __name__)


def _serialize_user(u: User) -> dict:
    return {'id': u.id, 'email': u.email, 'display_name': u.display_name}


def _serialize_workspace(w: Workspace) -> dict:
    return {'id': w.id, 'name': w.name, 'company_name': w.company_name}


@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.json or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    display_name = (data.get('display_name') or '').strip() or None
    company_name = (data.get('company_name') or '').strip() or None

    if not email or '@' not in email:
        return jsonify({'error': 'email_invalid'}), 400
    if len(password) < 6:
        return jsonify({'error': 'password_too_short', 'min': 6}), 400

    db = SessionLocal()
    try:
        existing = db.query(User).filter_by(email=email).first()
        if existing:
            return jsonify({'error': 'email_exists'}), 409

        # 自动创建 workspace
        ws = Workspace(
            name=company_name or f"{display_name or email.split('@')[0]} 的工作空间",
            company_name=company_name,
        )
        db.add(ws)
        db.flush()  # 拿到 ws.id

        user = User(
            email=email,
            password_hash=hash_password(password),
            display_name=display_name,
            workspace_id=ws.id,
        )
        db.add(user)
        db.commit()

        token = issue_token(user.id, ws.id)
        return jsonify({
            'token': token,
            'user': _serialize_user(user),
            'workspace': _serialize_workspace(ws),
        })
    finally:
        db.close()


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.json or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    if not email or not password:
        return jsonify({'error': 'missing_credentials'}), 400

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email=email).first()
        if not user or not verify_password(password, user.password_hash):
            return jsonify({'error': 'invalid_credentials'}), 401

        ws = user.workspace
        if not ws:
            # 兜底：用户没 workspace 就建一个
            ws = Workspace(name=f"{user.display_name or email.split('@')[0]} 的工作空间")
            db.add(ws); db.flush()
            user.workspace_id = ws.id
            db.commit()

        token = issue_token(user.id, ws.id)
        return jsonify({
            'token': token,
            'user': _serialize_user(user),
            'workspace': _serialize_workspace(ws),
        })
    finally:
        db.close()


@auth_bp.route('/me', methods=['GET'])
@require_auth
def me():
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=g.user_id).first()
        if not user:
            return jsonify({'error': 'user_not_found'}), 404
        ws = user.workspace
        return jsonify({
            'user': _serialize_user(user),
            'workspace': _serialize_workspace(ws) if ws else None,
        })
    finally:
        db.close()
