from flask import Blueprint, jsonify, request, g
import uuid
import json
from datetime import datetime
from app.storage.session_proxy import SessionsStore
from app.core.auth import require_auth

sessions_bp = Blueprint('sessions', __name__)

# Session store: MemoryStorage 或 SupabaseStorage 自动切换
# 接口仍兼容 dict（.get / [id] / in），但所有读写都过 storage
sessions_store = SessionsStore()


def _generate_welcome():
    """Call LLM to generate the interview opening message."""
    try:
        from app.agents.base_agent import BaseAgent
        agent = BaseAgent(temperature=0.5)
        system_prompt = agent.load_prompt('interview_extract.txt')
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "问题编号：Opening\n问题内容：访谈开场\n用户回答：（用户刚进入页面，还没有说话）"},
        ]
        response = agent.call_llm(messages)
        if '```json' in response:
            response = response.split('```json')[1].split('```')[0]
        elif '```' in response:
            response = response.split('```')[1].split('```')[0]
        result = json.loads(response.strip())
        return result.get('reply', '')
    except Exception as e:
        print(f'Welcome generation failed: {e}')
        return '你好！我是 Sparky，你的 AI 薪酬诊断助手。先简单介绍下你们公司吧？'


def _get_owned_session(session_id):
    """获取属于当前 workspace 的 session；不存在返回 (None, 404)，越权返回 (None, 403)"""
    session = sessions_store.get(session_id)
    if not session:
        return None, ('Session not found', 404)
    ws = session.get('workspace_id')
    # 兼容历史无 workspace_id 的 session：当前请求 workspace 拿过的会话直接挂上
    if ws is None:
        session['workspace_id'] = g.workspace_id
        return session, None
    if ws != g.workspace_id:
        return None, ('forbidden', 403)
    return session, None


@sessions_bp.route('/', methods=['POST'])
@require_auth
def create_session():
    """Create a new diagnostic session + DataSnapshot（持久化）"""
    session_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    # 建 session（legacy）+ 关联当前用户的 workspace
    sessions_store[session_id] = {
        'id': session_id,
        'snapshot_id': session_id,   # session_id == snapshot_id（一次诊断 = 一次快照）
        'workspace_id': g.workspace_id,
        'user_id': g.user_id,
        'status': 'created',
        'created_at': now,
        'employee_count': 0,
        'data_completeness_score': 0,
        'unlocked_modules': [],
        'cleansing_result': None,
        'matching_result': None,
        'interview_notes': None,
        'analysis_results': None,
    }

    # 同步建 DataSnapshot
    try:
        from app.storage import get_storage
        storage = get_storage()
        storage.save_user({
            'user_id': g.user_id,
            'org_name': None,
            'role': None,
            'created_at': now,
        })
        storage.save_snapshot({
            'snapshot_id': session_id,
            'user_id': g.user_id,
            'uploaded_at': now,
            'status': 'draft',
        })
    except Exception as e:
        print(f'[Session] snapshot init failed: {e}')

    resp = dict(sessions_store[session_id])
    resp['welcome'] = _generate_welcome()
    return jsonify(resp), 201

@sessions_bp.route('/<session_id>', methods=['GET'])
@require_auth
def get_session(session_id):
    """Get session details and current status"""
    session, err = _get_owned_session(session_id)
    if err:
        return jsonify({'error': err[0]}), err[1]
    return jsonify(session)

@sessions_bp.route('/<session_id>/status', methods=['GET'])
@require_auth
def get_status(session_id):
    """Poll session status"""
    session, err = _get_owned_session(session_id)
    if err:
        return jsonify({'error': err[0]}), err[1]
    return jsonify({
        'status': session['status'],
        'employee_count': session.get('employee_count', 0),
    })

@sessions_bp.route('/<session_id>/confirm', methods=['POST'])
@require_auth
def confirm_step(session_id):
    """Confirm a step (tax choice, grade mapping, function matching, etc.)"""
    session, err = _get_owned_session(session_id)
    if err:
        return jsonify({'error': err[0]}), err[1]

    data = request.json
    step = data.get('step')
    value = data.get('value')

    if step == 'tax_type':
        session.setdefault('confirmations', {})['tax_type'] = value
    elif step == 'grade_mapping':
        session.setdefault('confirmations', {})['grade_mapping'] = value
    elif step == 'function_matching':
        session.setdefault('confirmations', {})['function_matching'] = value
    elif step == 'revert_correction':
        session.setdefault('reverted_corrections', []).append(value)

    return jsonify({'status': 'confirmed', 'step': step})
