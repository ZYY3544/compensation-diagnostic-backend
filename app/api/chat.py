from flask import Blueprint, jsonify, request

chat_bp = Blueprint('chat', __name__)


@chat_bp.route('/<session_id>', methods=['POST'])
def chat(session_id):
    """Handle chat messages for a session"""
    from app.api.sessions import sessions_store

    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    data = request.json
    user_message = data.get('message', '')

    if not user_message:
        return jsonify({'error': 'Message is required'}), 400

    # Store conversation history
    history = session.setdefault('chat_history', [])
    history.append({'role': 'user', 'text': user_message})

    # For MVP: use SparkyAgent if API key is available, otherwise return a placeholder
    try:
        from app.agents.sparky_agent import SparkyAgent
        agent = SparkyAgent()
        report_context = session.get('analysis_results', {})
        response_text = agent.chat(user_message, context=report_context, conversation_history=history)
    except Exception:
        response_text = '目前暂时无法回答，请稍后再试。'

    history.append({'role': 'assistant', 'text': response_text})

    return jsonify({'response': response_text})
