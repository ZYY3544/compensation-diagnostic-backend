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

    # 每个 Q 的完整描述：主题 / 允许子话题 / 严禁话题 / extracted 字段名 / 访谈策略
    # AI 一次只看见一个 Q 的描述，看不到其他 Q 的存在
    Q_DESCRIPTIONS = {
        'Q1': {
            'name': '公司基本情况',
            'topic': '了解客户公司的业务、行业、规模、发展阶段',
            'field_name': 'company_profile',
            'allowed': [
                '主营业务、行业、产品或服务模式',
                '公司规模（员工数、营收量级）',
                '发展阶段（早期/成长期/成熟期/转型期）',
                '组织架构（事业部、BU、中后台、分子公司）',
                '地理布局（总部、分公司、海外办公室）',
                '关键里程碑（IPO、融资、重大业务变动）',
            ],
            'forbidden': [
                '未来战略、明年规划、转型方向、AI 转型',
                '薪酬诊断的核心诉求、留人/招人/控成本/公平性',
                '人才流失、员工离职情况',
                '核心岗位、人才市场竞争、关键人才',
                '薪酬管理、调薪机制、薪酬定位',
            ],
            'strategy': '暖场问题，让用户聊自己熟悉的东西，建立信任。如果信息不充分，追问组织结构、规模量级或业务模式细节。',
        },
        'Q2': {
            'name': '战略方向',
            'topic': '了解客户公司未来一年的业务战略重点和方向',
            'field_name': 'strategy',
            'allowed': [
                '未来 1-2 年的业务战略重点',
                '业务扩张计划、新市场开拓',
                '降本增效举措、组织优化',
                'AI 转型 / 数字化转型的程度和路径',
                '战略对组织或人才结构的潜在影响（只聊方向，不要聊具体薪酬）',
            ],
            'forbidden': [
                '当前业务和组织（之前已经聊过）',
                '薪酬诊断诉求、留人/招人/控成本/公平性',
                '具体的人才流失数据',
                '哪些岗位是核心',
                '薪酬策略、调薪、薪酬定位',
            ],
            'strategy': '战略决定薪酬哲学和付薪策略。如果用户提到 AI 转型，可以追问 AI 转型的具体落地路径；如果没提，可以追问有没有在关注这件事。',
        },
        'Q3': {
            'name': '诊断诉求',
            'topic': '了解客户这次做薪酬诊断最想解决的核心问题',
            'field_name': 'core_goal',
            'allowed': [
                '本次薪酬诊断最想解决的核心问题（留人、招人、控成本、公平性）',
                '诉求的优先级排序',
                '诉求的具体表现（用业务情境描述）',
                '诉求与之前提到的战略方向之间的张力或一致性',
            ],
            'forbidden': [
                '具体的流失部门、级别、去向（这是后面的话题）',
                '哪些岗位最关键（这是后面的话题）',
                '薪酬策略、调薪机制的具体做法（这是后面的话题）',
            ],
            'strategy': '结合用户之前已经提到的业务背景和战略方向，追问诉求的具体表现。如果用户选了多个诉求，帮他理优先级。',
        },
        'Q4': {
            'name': '流失情况',
            'topic': '了解客户公司近期的人才流失情况，包括哪些部门、什么级别、去向',
            'field_name': 'attrition',
            'allowed': [
                '近期流失明显的部门、级别',
                '流失的人才去向（同行、跨行、创业等）',
                '流失原因的初步判断',
                '如果流失不明显，转角度问平均司龄、员工活力、工作热情',
            ],
            'forbidden': [
                '哪些岗位是核心（这是下一个话题）',
                '薪酬竞争力数据、薪酬定位（这是后面的话题）',
                '战略和诊断诉求（已经聊过）',
            ],
            'strategy': '关联之前已经收集到的诊断诉求和战略方向。如果用户说没有明显流失，转换角度问司龄、积极性、工作热情等。',
        },
        'Q5': {
            'name': '核心职能',
            'topic': '了解客户公司最关键的业务职能和岗位，以及这些岗位的人才市场竞争情况',
            'field_name': 'core_functions',
            'allowed': [
                '哪些部门或岗位是业务的关键节点（走了业务就转不动的那种）',
                '这些岗位的人才市场竞争情况',
                '招聘难度和人才稀缺性',
                '如果之前提到的流失部门和核心职能重合，主动点出这个信号',
            ],
            'forbidden': [
                '具体的薪酬数字、调薪机制（这是下一个话题）',
                '业务战略（已经聊过）',
            ],
            'strategy': '关联之前用户提到的流失情况，如果流失部门跟核心职能重合，主动点出这个信号。',
        },
        'Q6': {
            'name': '薪酬管理现状',
            'topic': '了解客户当前的薪酬定位策略、调薪频率、预算和分配方式',
            'field_name': 'pay_strategy / raise_mechanism（可同时输出两个）',
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
            'strategy': '两个子话题（薪酬策略 + 调薪机制），通过追问自然覆盖。最后做整体收束：用 2-3 句话简短总结核心发现，引导用户确认纪要并上传数据。',
        },
    }

    # 题目顺序，用于查找下一题（仅在收束转场时给 AI 提示）
    Q_ORDER = ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6']

    def get_next_q(qid):
        try:
            idx = Q_ORDER.index(qid)
            if idx + 1 < len(Q_ORDER):
                return Q_DESCRIPTIONS[Q_ORDER[idx + 1]]
        except (ValueError, KeyError):
            pass
        return None

    current_q = Q_DESCRIPTIONS.get(question_id_upper)

    try:
        from app.agents.base_agent import BaseAgent
        agent = BaseAgent(temperature=0.3)
        core_prompt = agent.load_prompt('interview_extract.txt')

        # 动态拼 system_prompt：核心规则 + 当前 Q 的完整描述（其他 Q 完全隐藏）
        if current_q:
            allowed_str = '\n'.join(f'  - {x}' for x in current_q['allowed'])
            forbidden_str = '\n'.join(f'  - {x}' for x in current_q['forbidden'])
            current_q_block = (
                f"\n\n========== 当前问题：{question_id} {current_q['name']} ==========\n"
                f"主题：{current_q['topic']}\n"
                f"extracted 字段名（必须使用这个，不能用其他）：{current_q['field_name']}\n\n"
                f"✅ 允许子话题（你的追问必须落在这个范围内）：\n{allowed_str}\n\n"
                f"⛔ 严禁话题（绝对不要碰）：\n{forbidden_str}\n\n"
                f"访谈策略：{current_q['strategy']}\n"
                f"========== 当前问题描述结束 ==========\n"
            )
            system_prompt = core_prompt + current_q_block
        else:
            # Opening 等非 Q1-Q6 的请求
            system_prompt = core_prompt

        if is_follow_up and follow_up_question:
            user_content = f"问题编号：{question_id}（追问回答）\nSparky 上一条追问的问题：{follow_up_question}\n用户回答：{user_answer}"
        else:
            user_content = f"问题编号：{question_id}\n用户回答：{user_answer}"
        if previous_value:
            user_content += f"\n\n该字段已有的提炼内容（仅用于合并到 extracted.value 中，不要在 reply 中重复这些信息）：\n{previous_value}"
        if context:
            user_content += f"\n\n之前的访谈上下文：\n{context}"

        # 仅在最后一轮（强制收束）时，告诉 AI 下一个话题是什么，方便它写过渡句
        if should_force_close:
            next_q = get_next_q(question_id_upper)
            if next_q:
                user_content += (
                    f"\n\n【系统提示：这是当前问题的最后一轮，你必须在这次回复中做收束，"
                    f"并自然过渡到下一个话题「{next_q['name']}」（{next_q['topic']}）。"
                    f"过渡句要用当前话题的结论或关键信息作为引子，让两个话题之间有因果或递进关系，不要生硬拼接。"
                    f"follow_up 必须为 false。】"
                )
            else:
                # Q6 的最后一轮，没有下一题
                user_content += (
                    "\n\n【系统提示：这是访谈的最后一轮，请用 2-3 句话整体收束：简短总结这次访谈的核心发现，"
                    "引导用户确认纪要并上传薪酬数据进行诊断。follow_up 必须为 false。】"
                )

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
