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

    return jsonify({'response': '\n'.join(line.strip() for line in response_text.split('\n'))})


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
    previous_value = data.get('previous_value', '')  # 该字段已有的 value
    is_follow_up = data.get('is_follow_up', False)  # 是否是追问
    round_num = data.get('round', 1)  # 当前是第几轮回答：1=首次, 2=第一次追问回答, 3=第二次追问回答 ...
    follow_up_question = data.get('follow_up_question', '')  # Sparky 的追问问题
    context = data.get('context', '')  # 之前的访谈上下文

    if not user_answer:
        return jsonify({'error': 'Answer is required'}), 400

    # 判定是否需要强制收束
    # 非 Q6：round>=3 强制收束（允许 2 次追问）
    # Q6：round>=4 才强制收束（Q6 允许 2-3 轮）
    question_id_upper = (question_id or '').upper()
    if question_id_upper == 'Q6':
        should_force_close = round_num >= 4
    elif question_id_upper.startswith('Q'):
        should_force_close = round_num >= 3
    else:
        should_force_close = False

    # 每个 Q 的边界规范：允许子话题 / 严禁话题 / 跨界处理
    Q_BOUNDARIES = {
        'Q1': {
            'name': '公司基本情况',
            'allowed': [
                '主营业务、行业、产品或服务模式',
                '公司规模（员工数、营收量级）',
                '发展阶段（早期/成长期/成熟期/转型期）',
                '组织架构（事业部、BU、中后台、分子公司）',
                '地理布局（总部、分公司、海外办公室）',
                '关键里程碑（IPO、融资、重大业务变动）',
            ],
            'forbidden': [
                '未来战略、明年规划、转型方向（属于 Q2）',
                '薪酬诊断的核心诉求（属于 Q3）',
                '人才流失、员工离职情况（属于 Q4）',
                '核心岗位、人才市场竞争（属于 Q5）',
                '薪酬管理、调薪机制、薪酬定位（属于 Q6）',
            ],
        },
        'Q2': {
            'name': '战略方向',
            'allowed': [
                '未来 1-2 年的业务战略重点',
                '业务扩张计划、新市场开拓',
                '降本增效举措、组织优化',
                'AI 转型 / 数字化转型的程度和路径',
                '战略对人才结构的潜在影响（不要细聊薪酬）',
            ],
            'forbidden': [
                '当前业务和组织（属于 Q1，已经聊过）',
                '薪酬诊断的核心诉求（属于 Q3）',
                '具体的人才流失数据（属于 Q4）',
                '哪些岗位是核心（属于 Q5）',
                '薪酬策略、调薪（属于 Q6）',
            ],
        },
        'Q3': {
            'name': '诊断诉求',
            'allowed': [
                '本次薪酬诊断最想解决的核心问题（留人、招人、控成本、公平性）',
                '诉求的优先级排序',
                '诉求的具体表现（用业务情境描述，不要细究流失数据）',
                '诉求与之前提到的战略方向之间的张力或一致性',
            ],
            'forbidden': [
                '具体的流失部门、级别、去向（属于 Q4）',
                '哪些岗位最关键（属于 Q5）',
                '薪酬策略、调薪机制的具体做法（属于 Q6）',
            ],
        },
        'Q4': {
            'name': '流失情况',
            'allowed': [
                '近期流失明显的部门、级别',
                '流失的人才去向（同行、跨行、创业等）',
                '流失原因的初步判断',
                '如果流失不明显，转角度问平均司龄、员工活力、工作热情',
            ],
            'forbidden': [
                '哪些岗位是核心（属于 Q5）',
                '薪酬竞争力数据、薪酬定位（属于 Q6）',
                '战略和诉求（已经聊过）',
            ],
        },
        'Q5': {
            'name': '核心职能',
            'allowed': [
                '哪些部门或岗位是业务的关键节点（走了业务就转不动的那种）',
                '这些岗位的人才市场竞争情况',
                '招聘难度和人才稀缺性',
                '如果流失部门和核心职能重合，主动点出这个信号',
            ],
            'forbidden': [
                '具体的薪酬数字、调薪机制（属于 Q6）',
                '业务战略（已经聊过）',
            ],
        },
        'Q6': {
            'name': '薪酬管理现状',
            'allowed': [
                '薪酬定位策略（领先 / 跟随 / 滞后市场）',
                '是否有岗位差异化定薪',
                '薪酬数据来源（市场报告、自己摸索等）',
                '调薪频率、调薪预算、调薪分配方式',
                '固定 vs 浮动的结构',
            ],
            'forbidden': [
                '业务、战略、流失等其他话题（已经聊过）',
            ],
        },
    }
    boundary = Q_BOUNDARIES.get(question_id_upper)

    try:
        from app.agents.base_agent import BaseAgent
        agent = BaseAgent(temperature=0.3)
        system_prompt = agent.load_prompt('interview_extract.txt')

        if is_follow_up and follow_up_question:
            user_content = f"问题编号：{question_id}（追问）\nSparky 上一条追问的问题：{follow_up_question}\n用户回答：{user_answer}"
        else:
            user_content = f"问题编号：{question_id}\n问题内容：{question_text}\n用户回答：{user_answer}"
        if previous_value:
            user_content += f"\n\n该字段已有的提炼内容（仅用于合并到 extracted.value 中，不要在 reply 中重复这些信息）：\n{previous_value}"
        if context:
            user_content += f"\n\n之前的访谈上下文：\n{context}"

        # 注入当前 Q 的边界规范，强制 AI 的追问问题落在允许范围内
        if boundary:
            allowed_str = '\n'.join(f'  - {x}' for x in boundary['allowed'])
            forbidden_str = '\n'.join(f'  - {x}' for x in boundary['forbidden'])
            user_content += (
                f"\n\n【{question_id} 边界规范——这是硬性约束，优先级最高】\n"
                f"当前问题：{boundary['name']}\n\n"
                f"✅ 你的追问问题必须落在以下子话题范围内：\n{allowed_str}\n\n"
                f"⛔ 严禁触碰以下话题（这些后面会专门聊）：\n{forbidden_str}\n\n"
                f"🚧 如果用户的回答带出了禁区话题，简短确认后说\"这个我们后面会专门聊\"，"
                f"然后把追问拉回到允许范围内。绝对不要顺着用户带出的禁区话题继续追问。"
            )

        if should_force_close:
            user_content += "\n\n【系统提示：这是当前问题的最后一轮，你必须在这次回复中做收束，自然过渡到下一个问题。follow_up 必须为 false。】"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        response = agent.call_llm(messages)

        # Parse JSON
        if '```json' in response:
            response = response.split('```json')[1].split('```')[0]
        elif '```' in response:
            response = response.split('```')[1].split('```')[0]

        result = json.loads(response.strip())

        # Clean all string values from AI output: strip each line
        def clean_text(s):
            return '\n'.join(line.strip() for line in s.split('\n'))

        extracted = result.get('extracted', [])
        if isinstance(extracted, list):
            for item in extracted:
                if isinstance(item, dict) and 'value' in item:
                    item['value'] = clean_text(item['value'])
        reply = clean_text(result.get('reply', '好的，了解了。'))

        # 强制规则：基于 round 兜底
        # round=1                  → 强制 follow_up=true（必须追问一轮）
        # Q6 且 round in {2,3}     → 尊重 AI（Q6 可追问 2-3 轮）
        # 非 Q6 且 round=2         → 尊重 AI（允许 AI 自己决定再追问一次或过渡）
        # 非 Q6 且 round>=3        → 强制 follow_up=false
        # Q6 且 round>=4           → 强制 follow_up=false
        ai_follow_up = result.get('follow_up', False)
        if round_num == 1:
            follow_up_value = True
        elif should_force_close:
            follow_up_value = False
        else:
            follow_up_value = ai_follow_up

        print(f'[Interview Extract] Q={question_id}, round={round_num}, force_close={should_force_close}, ai_follow_up={ai_follow_up}, final={follow_up_value}')

        return jsonify({
            'extracted': extracted,
            'reply': reply,
            'follow_up': follow_up_value,
        })
    except Exception as e:
        print(f'Extract failed: {e}')
        import traceback
        traceback.print_exc()
        # Fallback: use raw answer as value
        return jsonify({
            'extracted': [{'field_name': question_id.lower().replace('q', 'field_'), 'value': user_answer}],
            'reply': '好的，了解了。',
            'follow_up': False,
        })


@chat_bp.route('/findings', methods=['POST'])
def generate_findings():
    """Generate key findings from interview notes"""
    data = request.json
    interview_notes = data.get('interview_notes', '')

    if not interview_notes:
        return jsonify({'error': 'interview_notes is required'}), 400

    try:
        from app.agents.base_agent import BaseAgent
        agent = BaseAgent(temperature=0.3)
        prompt_template = agent.load_prompt('interview_findings.txt')
        prompt = prompt_template.replace('{interview_notes}', interview_notes)

        messages = [
            {"role": "user", "content": prompt}
        ]

        findings = agent.call_llm(messages)
        return jsonify({'findings': findings.strip()})
    except Exception as e:
        print(f'Findings generation failed: {e}')
        return jsonify({'findings': '', 'error': str(e)}), 500


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
            full_response = '\n'.join(line.strip() for line in agent.chat(user_message, context=report_context, conversation_history=history).split('\n'))

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
