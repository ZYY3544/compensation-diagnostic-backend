"""
Session 所有权 + workspace 隔离助手。

所有需要从 session_id 取 session 的 endpoint 都用 owned_session_or_403，
确保用户只能访问自己 workspace 下的 session，不能用别人的 UUID 串数据。
"""
from flask import g, jsonify
from app.api.sessions import sessions_store


def owned_session_or_403(session_id: str):
    """
    返回 (session, error_response)。
    成功：(session_dict, None)
    失败：(None, flask Response)，调用方直接 return 这个 response。

    历史会话（无 workspace_id 字段）会自动挂到当前 workspace 上做兼容
    （部署后老 session 第一次被读到的瞬间被认领）。
    """
    session = sessions_store.get(session_id)
    if not session:
        return None, (jsonify({'error': 'Session not found'}), 404)
    ws = session.get('workspace_id')
    if ws is None:
        # 兼容：老 session 没 workspace_id，第一次访问的当前 workspace 认领
        session['workspace_id'] = g.workspace_id
        return session, None
    if ws != g.workspace_id:
        return None, (jsonify({'error': 'forbidden'}), 403)
    return session, None
