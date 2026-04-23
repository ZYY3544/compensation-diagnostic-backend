"""
JWT auth：register / login / verify。

- 密码 bcrypt hash 存
- 登录返回 JWT，前端塞 localStorage
- @require_auth 装饰器从 Authorization: Bearer <token> 解出 user_id + workspace_id
  挂到 flask.g 上，视图函数可以直接读
"""
import os
import time
import bcrypt
import jwt as pyjwt
from functools import wraps
from flask import request, jsonify, g

JWT_SECRET = os.getenv('JWT_SECRET', 'dev-jwt-secret-please-change-in-prod')
JWT_ALGO = 'HS256'
JWT_EXPIRE_DAYS = 30

# 开发期开关：AUTH_DISABLED=true 时所有 @require_auth 路由直接放行，
# 注入固定 admin 身份。上线前删掉这个环境变量即可启用真实登录。
AUTH_DISABLED = os.getenv('AUTH_DISABLED', '').lower() == 'true'
ADMIN_USER_ID = 'usr_admin'
ADMIN_WORKSPACE_ID = 'ws_admin'


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False


def issue_token(user_id: str, workspace_id: str) -> str:
    """签 JWT，30 天过期"""
    now = int(time.time())
    payload = {
        'sub': user_id,
        'ws': workspace_id,
        'iat': now,
        'exp': now + JWT_EXPIRE_DAYS * 86400,
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def decode_token(token: str) -> dict | None:
    """返回 payload；签名错或过期返回 None"""
    try:
        return pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except pyjwt.PyJWTError:
        return None


def require_auth(fn):
    """
    路由装饰器：要求 Authorization: Bearer <token>。
    成功后 g.user_id / g.workspace_id 可用，view 函数可直接 from flask import g 读。
    失败返回 401。
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if AUTH_DISABLED:
            g.user_id = ADMIN_USER_ID
            g.workspace_id = ADMIN_WORKSPACE_ID
            return fn(*args, **kwargs)
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify({'error': 'unauthorized', 'reason': 'missing_token'}), 401
        token = auth[7:].strip()
        payload = decode_token(token)
        if not payload:
            return jsonify({'error': 'unauthorized', 'reason': 'invalid_token'}), 401
        g.user_id = payload.get('sub')
        g.workspace_id = payload.get('ws')
        if not g.user_id or not g.workspace_id:
            return jsonify({'error': 'unauthorized', 'reason': 'malformed_token'}), 401
        return fn(*args, **kwargs)
    return wrapper
