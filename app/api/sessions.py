from flask import Blueprint, jsonify, request
import uuid
import json
from datetime import datetime

sessions_bp = Blueprint('sessions', __name__)

# In-memory store for MVP (replace with Supabase later)
sessions_store = {}


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


@sessions_bp.route('/', methods=['POST'])
def create_session():
    """Create a new diagnostic session"""
    session_id = str(uuid.uuid4())
    sessions_store[session_id] = {
        'id': session_id,
        'status': 'created',
        'created_at': datetime.utcnow().isoformat(),
        'employee_count': 0,
        'data_completeness_score': 0,
        'unlocked_modules': [],
        'cleansing_result': None,
        'matching_result': None,
        'interview_notes': None,
        'analysis_results': None,
    }
    resp = dict(sessions_store[session_id])
    resp['welcome'] = _generate_welcome()
    return jsonify(resp), 201

@sessions_bp.route('/<session_id>', methods=['GET'])
def get_session(session_id):
    """Get session details and current status"""
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    return jsonify(session)

@sessions_bp.route('/<session_id>/status', methods=['GET'])
def get_status(session_id):
    """Poll session status"""
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    return jsonify({
        'status': session['status'],
        'employee_count': session.get('employee_count', 0),
    })

@sessions_bp.route('/<session_id>/confirm', methods=['POST'])
def confirm_step(session_id):
    """Confirm a step (tax choice, grade mapping, function matching, etc.)"""
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

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
