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

    # For MVP: return mock response
    response = get_mock_response(user_message, stage)

    return jsonify({
        'role': 'assistant',
        'content': response,
    })


def get_mock_response(message, stage):
    """Mock Sparky response based on keywords"""
    lower = message.lower()

    if '销售' in lower:
        return '销售 L4-L5 的 CR 值仅 0.84-0.88，低于市场中位值 12-16%。如果这是你们的核心创收团队，建议将调薪预算的 40% 优先倾斜到这个群体。'
    elif '建议' in lower or '怎么办' in lower or '预算' in lower:
        return '基于诊断结果，建议调薪优先级：① 销售 L4-L5 ② HR L3-L5 ③ 管理岗溢价调整。如果总预算 8%，建议按 4:2.5:1.5 分配。'
    elif '研发' in lower:
        return '研发团队整体竞争力良好（CR 1.02-1.07），整体保持即可，不建议再加大投入。'
    elif '管理' in lower or '经理' in lower:
        return '管理岗溢价偏低是个结构性问题。L7 管理岗仅比专业岗高 7%，建议引入管理岗专项津贴。'
    else:
        return '基于目前的诊断数据来看，建议你重点关注外部竞争力模块中各职能的竞争力差异，这可能是当前最需要优先解决的问题。'
