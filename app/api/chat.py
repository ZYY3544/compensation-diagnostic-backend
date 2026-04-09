from flask import Blueprint, jsonify, request, Response, stream_with_context
import json

chat_bp = Blueprint('chat', __name__)


@chat_bp.route('/<session_id>', methods=['POST'])
def chat(session_id):
    """Non-streaming chat endpoint (fallback)"""
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

    try:
        from app.agents.sparky_agent import SparkyAgent
        agent = SparkyAgent()
        report_context = session.get('analysis_results', {})
        response_text = agent.chat(user_message, context=report_context, conversation_history=history)
    except Exception:
        response_text = '抱歉，遇到了一些问题。'

    history.append({'role': 'assistant', 'text': response_text})

    return jsonify({'response': response_text})


@chat_bp.route('/<session_id>/extract', methods=['POST'])
def extract_interview_answer(session_id):
    """Extract structured info from free-text interview answer using AI"""
    from app.api.sessions import sessions_store

    # Session is optional for extract - allow "_" as placeholder
    if session_id != '_':
        session = sessions_store.get(session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404

    data = request.json
    user_answer = data.get('answer', '')
    question_id = data.get('question_id', '')  # Q1-Q6
    question_text = data.get('question_text', '')

    if not user_answer:
        return jsonify({'error': 'Answer is required'}), 400

    try:
        from app.agents.base_agent import BaseAgent
        agent = BaseAgent(temperature=0.1)
        system_prompt = agent.load_prompt('interview_extract.txt')

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"问题编号：{question_id}\n问题内容：{question_text}\n用户回答：{user_answer}"}
        ]

        response = agent.call_llm(messages)

        # Parse JSON
        if '```json' in response:
            response = response.split('```json')[1].split('```')[0]
        elif '```' in response:
            response = response.split('```')[1].split('```')[0]

        result = json.loads(response.strip())

        return jsonify({
            'extracted': result.get('extracted', {}),
            'reply': result.get('reply', '好的，了解了。'),
        })
    except Exception as e:
        print(f'Extract failed: {e}')
        # Fallback: use raw answer as value
        return jsonify({
            'extracted': {'field_name': question_id, 'value': user_answer},
            'reply': '好的，了解了。',
        })


@chat_bp.route('/<session_id>/stream', methods=['POST'])
def chat_stream(session_id):
    """SSE streaming chat endpoint"""
    from app.api.sessions import sessions_store

    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    data = request.json
    user_message = data.get('message', '')

    if not user_message:
        return jsonify({'error': 'Message is required'}), 400

    history = session.setdefault('chat_history', [])
    history.append({'role': 'user', 'text': user_message})

    def generate():
        try:
            from app.agents.sparky_agent import SparkyAgent
            agent = SparkyAgent()
            report_context = session.get('analysis_results', {})

            # Get full response (non-streaming from LLM for now)
            full_response = agent.chat(user_message, context=report_context, conversation_history=history)

            # Simulate streaming by sending chunks
            chunk_size = 3  # characters per chunk
            for i in range(0, len(full_response), chunk_size):
                chunk = full_response[i:i + chunk_size]
                yield f"data: {json.dumps({'type': 'text', 'content': chunk}, ensure_ascii=False)}\n\n"

            history.append({'role': 'assistant', 'text': full_response})
        except Exception:
            error_msg = '抱歉，遇到了一些问题。'
            yield f"data: {json.dumps({'type': 'text', 'content': error_msg}, ensure_ascii=False)}\n\n"
            history.append({'role': 'assistant', 'text': error_msg})

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )
