from flask import Blueprint, jsonify, request

chat_bp = Blueprint('chat', __name__)


@chat_bp.route('/<session_id>/message', methods=['POST'])
def send_message(session_id):
    """Send a message to Sparky and get a response"""
    from app.api.sessions import sessions_store

    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    data = request.json
    user_message = data.get('message', '')
    stage = data.get('stage', 'chat')
    conversation_history = data.get('history', [])

    try:
        if stage == 'interview':
            from app.agents.sparky_agent import SparkyAgent
            agent = SparkyAgent()
            context = session.get('parse_result', {})
            response = agent.chat(user_message, context=context, conversation_history=conversation_history)
        elif stage == 'report':
            from app.agents.insight_agent import InsightChatAgent
            agent = InsightChatAgent()
            report_context = session.get('analysis_results', {})
            response = agent.chat(user_message, report_context=report_context, conversation_history=conversation_history)
        else:
            from app.agents.sparky_agent import SparkyAgent
            agent = SparkyAgent()
            response = agent.chat(user_message, conversation_history=conversation_history)
    except Exception as e:
        response = f'抱歉，遇到了一些问题：{str(e)}'

    return jsonify({
        'role': 'assistant',
        'content': response,
    })
