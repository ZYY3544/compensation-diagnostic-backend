from flask import Blueprint, jsonify, request
import uuid
from datetime import datetime

sessions_bp = Blueprint('sessions', __name__)

# In-memory store for MVP (replace with Supabase later)
sessions_store = {}

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
    return jsonify(sessions_store[session_id]), 201

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
