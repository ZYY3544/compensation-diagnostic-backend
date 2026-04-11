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

    # 每个 Q 的完整描述：主题 / 允许子话题 / 严禁话题 / extracted 字段名 / 访谈策略 / 核心关键词
    # AI 一次只看见一个 Q 的描述，看不到其他 Q 的存在
    # keywords 是一组核心关键词，用于后端启发式检测 reply 是否真的过渡到了这一题
    Q_DESCRIPTIONS = {
        'Q1': {
            'name': '公司基本情况',
            'topic': '了解客户公司的业务、行业、规模、发展阶段',
            'field_names': ['company_profile'],
            'keywords': ['公司', '业务', '规模', '组织', '阶段', '行业', '员工'],
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
            'field_names': ['strategy'],
            'keywords': ['战略', '方向', '规划', '扩张', '转型', 'AI', '增效', '市场', '未来'],
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
            'field_names': ['core_goal'],
            'keywords': ['诊断', '诉求', '问题', '留人', '招人', '控成本', '公平', '想解决', '核心问题'],
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
            'field_names': ['attrition'],
            'keywords': ['流失', '离职', '离开', '人员变动', '不稳定', '司龄', '稳定性'],
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
            'field_names': ['core_functions'],
            'keywords': ['核心', '关键', '岗位', '职能', '人才', '招聘', '稀缺', '走了', '关键节点'],
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
            'topic': '了解客户当前的薪酬体系和调薪机制现状，两个重点方向：薪酬定位策略 + 调薪机制',
            'field_names': ['pay_management'],
            'allowed': [
                '薪酬定位策略（领先 / 跟随 / 滞后市场）和选择的原因',
                '是否有岗位差异化定薪、不同岗位族的策略区分',
                '薪酬数据来源（市场报告、自己摸索、同行交流等）',
                '调薪频率、调薪预算规模、预算分配方式',
                '固定 vs 浮动薪酬结构，年终奖占比',
                '是否有明确的定薪/调薪机制文件或流程',
            ],
            'forbidden': [
                '业务、战略、流失等其他话题（已经聊过）',
            ],
            'strategy': '这是访谈最后一题，有两个重点方向（薪酬定位策略 + 调薪机制），通过 2-3 轮追问自然覆盖这两方面。最后做整体收束：用 2-3 句话简短总结整个访谈的核心发现，引导用户确认纪要并上传数据。',
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
            field_names = current_q['field_names']
            if len(field_names) == 1:
                field_name_block = (
                    f"extracted 字段名（必须严格使用这个英文 key，不能用任何其他写法）：\n"
                    f"  - {field_names[0]}"
                )
            else:
                field_list = '\n'.join(f'  - {fn}' for fn in field_names)
                field_name_block = (
                    f"extracted 字段名（必须严格使用下面列出的英文 key 之一，不能用其他写法，不能把两个合并在一起）：\n"
                    f"{field_list}\n"
                    f"你可以在一次回复中同时输出多条 extracted（每条使用不同的 field_name），"
                    f"分别记录对应子话题的信息。"
                )
            current_q_block = (
                f"\n\n========== 当前问题：{question_id} {current_q['name']} ==========\n"
                f"主题：{current_q['topic']}\n"
                f"{field_name_block}\n\n"
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

        # round >= 2 时，告诉 AI 下一个话题是什么（任何可能过渡的轮次都需要）
        # 同时强制 AI 保持 reply 内容和 follow_up 字段一致
        if round_num >= 2:
            next_q = get_next_q(question_id_upper)
            next_q_hint = (
                f"下一个话题是「{next_q['name']}」（{next_q['topic']}）"
                if next_q else "这是访谈的最后一题，没有下一题"
            )

            if should_force_close:
                # 强制收束：必须 follow_up=false 并写过渡
                if next_q:
                    user_content += (
                        f"\n\n【系统提示：这是当前问题的最后一轮，必须收束。\n"
                        f"{next_q_hint}。\n"
                        f"你必须：① 把 follow_up 设为 false；② 在 reply 里用当前话题的结论或关键信息作为引子，"
                        f"自然过渡到下一个话题，不要生硬拼接。reply 末尾必须是一个引出下一话题的问题。】"
                    )
                else:
                    user_content += (
                        "\n\n【系统提示：这是访谈的最后一轮，请用 2-3 句话整体收束：简短总结这次访谈的核心发现，"
                        "引导用户确认纪要并上传薪酬数据进行诊断。follow_up 必须为 false。】"
                    )
            else:
                # round=2 等中间轮次：AI 自由选择，但必须保证 reply 和 follow_up 一致
                user_content += (
                    f"\n\n【系统提示：现在是第 {round_num} 轮回答。{next_q_hint}。\n"
                    f"你有两个选择，必须严格保证 reply 和 follow_up 字段一致：\n"
                    f"  ① 继续追问当前话题：follow_up=true，reply 必须写一个深入的追问问题（落在当前话题的允许子话题内）。\n"
                    f"  ② 过渡到下一个话题：follow_up=false，reply 必须用当前话题的结论作引子，自然过渡到下一个话题，"
                    f"reply 末尾必须是一个引出下一话题的问题。绝对不允许 follow_up=false 但 reply 还在追问当前话题。】"
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
        # round=1                       → 强制 follow_up=true（必须追问一轮）
        # Q6 且 round<=2                → 强制 follow_up=true（Q6 有两个子话题，必须至少 2 轮追问才能覆盖完）
        # Q6 且 round=3                 → 尊重 AI（可选的第 3 轮）
        # Q6 且 round>=4                → 强制 follow_up=false
        # 非 Q6 且 round=2              → 尊重 AI
        # 非 Q6 且 round>=3             → 强制 follow_up=false
        ai_follow_up = result.get('follow_up', False)
        if round_num == 1:
            follow_up_value = True
        elif question_id_upper == 'Q6' and round_num <= 2:
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


@chat_bp.route('/review', methods=['POST'])
def review_interview():
    """闭环 1：Sparky 自主修订访谈纪要（只做安全操作），然后告诉用户改了什么。

    安全操作：格式整理 / 重复合并 / 矛盾标记
    禁止：删内容 / 改语义 / 添加新信息
    """
    data = request.json
    interview_notes = data.get('interview_notes', '')

    if not interview_notes:
        return jsonify({'error': 'interview_notes is required'}), 400

    try:
        from app.agents.base_agent import BaseAgent
        agent = BaseAgent(temperature=0.3)
        prompt = (
            "你是 Sparky，刚完成了一轮 6 题的业务访谈。以下是当前纪要的完整内容：\n\n"
            f"{interview_notes}\n\n"
            "字段编号映射（输出 updates 时必须使用这些英文 field_name）：\n"
            "- company_profile = 公司基本情况\n"
            "- strategy = 战略方向\n"
            "- core_goal = 诊断诉求\n"
            "- attrition = 流失情况\n"
            "- core_functions = 核心职能\n"
            "- pay_management = 薪酬管理现状（包含薪酬定位策略 + 调薪机制两个方向）\n\n"
            "你的任务是做三件事，对应输出 JSON 中的三个字段：\n\n"
            "【第一件事 — updates】自主修订纪要。你只能做这三种安全操作：\n"
            "  1. 格式整理：统一换行分隔、补齐 **加粗** 标记、移除多余空白、修正明显的排版混乱\n"
            "  2. 重复合并：同一个字段里出现明显重复的描述，合并成一条\n"
            "  3. 矛盾标记：如果发现字段之间有明显矛盾（比如规模前后不一致），"
            "在对应 value 的开头用【⚠️待确认：具体描述】标出来让用户看到\n\n"
            "绝对禁止（违反就是产品事故）：\n"
            "  ❌ 删除任何有实质信息的内容，即使你觉得它不重要、不相关\n"
            "  ❌ 改变任何陈述的语义，即使你觉得换个说法更好\n"
            "  ❌ 添加原文里没有的新信息、新判断、新数据、新推理\n"
            "  ❌ 跨字段搬运内容（比如把 Q1 的东西挪到 Q2）\n\n"
            "【第二件事 — summary】用 3-5 句话做整体总结。内容是你对整个访谈的专业判断："
            "客户的业务、战略和薪酬管理之间的核心矛盾、值得关注的信号、结构化的观察。"
            "语言要像资深顾问的复盘，不要客套、不要寒暄，直接给判断。150-220 字。\n\n"
            "【第三件事 — reply】用 2-3 句话告诉用户你在纪要上动了什么（比如"
            "\"我把战略方向那块的格式整理了一下，另外发现规模前后提的数字不一样，我标了一下让你看看\"）。"
            "如果一个字段都没改，直接说\"纪要整理下来挺完整的，没什么需要修正的地方\"。"
            "然后问用户还有没有要补充或修改的。80-120 字。\n\n"
            "重要：summary 和 reply 是两条独立的消息，会被前端分别展示。\n"
            "- summary 只包含\"整体总结/专业判断\"，不要包含\"我改了什么\"或\"问用户补充\"\n"
            "- reply 只包含\"我改了什么 + 问用户补充\"，不要包含整体总结的内容\n"
            "- 两者内容不要重复\n\n"
            "输出 JSON 格式：\n"
            "{\n"
            '  "updates": [\n'
            '    {"field_name": "strategy", "value": "修订后的完整 value（全量，不是 diff）"}\n'
            "  ],\n"
            '  "summary": "整体总结，3-5 句话，150-220 字",\n'
            '  "reply": "说你改了什么 + 问用户补充，2-3 句话，80-120 字"\n'
            "}\n\n"
            "注意：\n"
            "- updates 列表只包含你真的修订了的字段。没改的字段不要出现在 updates 里\n"
            "- 如果完全没什么需要改的，updates 返回空数组 []\n"
            "- field_name 必须是上面列出的 6 个之一，不能自创\n"
            "- 只输出 JSON，不要其他文字，不要 markdown 代码块\n"
            "- 用中文"
        )
        messages = [
            {"role": "user", "content": prompt}
        ]
        response = agent.call_llm(messages)

        # Parse JSON
        if '```json' in response:
            response = response.split('```json')[1].split('```')[0]
        elif '```' in response:
            response = response.split('```')[1].split('```')[0]
        result = json.loads(response.strip())

        def clean_text(s):
            return '\n'.join(line.strip() for line in s.split('\n'))

        updates = result.get('updates', [])
        if isinstance(updates, list):
            for item in updates:
                if isinstance(item, dict) and 'value' in item:
                    item['value'] = clean_text(item['value'])
        summary = clean_text(result.get('summary', ''))
        reply = clean_text(result.get('reply', '纪要整理下来挺完整的。你看看还有什么想补充或者修改的？'))

        print(f'[Interview Review] updates_count={len(updates) if isinstance(updates, list) else 0}, summary_len={len(summary)}, reply_len={len(reply)}')

        return jsonify({
            'updates': updates,
            'summary': summary,
            'reply': reply,
        })
    except Exception as e:
        print(f'Review failed: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({
            'updates': [],
            'summary': '',
            'reply': '纪要整理下来挺完整的。你看看右边的卡片，有没有想补充或者修改的地方？没问题的话点下方「确认纪要 →」继续。'
        })


@chat_bp.route('/supplement', methods=['POST'])
def process_supplement():
    """处理用户在审阅阶段的补充信息：AI 判断归属到哪张卡片并更新 value"""
    data = request.json
    interview_notes = data.get('interview_notes', '')
    user_supplement = data.get('supplement', '')

    if not user_supplement:
        return jsonify({'error': 'supplement is required'}), 400

    try:
        from app.agents.base_agent import BaseAgent
        agent = BaseAgent(temperature=0.3)
        prompt = (
            "你是 Sparky，正在协助客户补充薪酬诊断访谈的纪要。用户现在补充了一些新信息，"
            "你需要判断这些信息应该归属到哪个字段，并整合进原有内容。\n\n"
            "可用的 field_name 有 7 个（严格使用，不要用其他）：\n"
            "  - company_profile: 公司基本情况\n"
            "  - strategy: 战略方向\n"
            "  - core_goal: 诊断诉求\n"
            "  - attrition: 流失情况\n"
            "  - core_functions: 核心职能\n"
            "  - pay_management: 薪酬管理现状（薪酬定位策略 + 调薪机制）\n\n"
            "当前纪要内容：\n"
            f"{interview_notes}\n\n"
            "用户补充：\n"
            f"{user_supplement}\n\n"
            "请做三件事：\n"
            "1. 分析用户补充内容应该归属到哪个 field_name（可能是 1 个或多个）\n"
            "2. 基于原有内容 + 用户补充，生成更新后的 value（保留原有关键信息，用换行分隔不同维度，关键词用 **加粗** 标记）\n"
            "3. 用 1-2 句话确认，问用户还有没有其他想补充的，比如「好的，我把战略方向那块更新了一下。还有其他想补充的吗？」\n\n"
            "输出 JSON 格式：\n"
            "{\n"
            "  \"updates\": [\n"
            "    {\"field_name\": \"strategy\", \"value\": \"更新后的完整 value 内容\"}\n"
            "  ],\n"
            "  \"reply\": \"给用户的回应\"\n"
            "}\n\n"
            "只输出 JSON，不要其他文字。如果用户的补充不明确或者和现有纪要没关联，"
            "返回空的 updates 列表和一句友好的澄清问话。"
        )
        messages = [
            {"role": "user", "content": prompt}
        ]
        response = agent.call_llm(messages)

        # Parse JSON
        if '```json' in response:
            response = response.split('```json')[1].split('```')[0]
        elif '```' in response:
            response = response.split('```')[1].split('```')[0]
        result = json.loads(response.strip())

        # Clean text
        def clean_text(s):
            return '\n'.join(line.strip() for line in s.split('\n'))

        updates = result.get('updates', [])
        if isinstance(updates, list):
            for item in updates:
                if isinstance(item, dict) and 'value' in item:
                    item['value'] = clean_text(item['value'])
        reply = clean_text(result.get('reply', '好的，我记下了。还有其他想补充的吗？'))

        return jsonify({
            'updates': updates,
            'reply': reply,
        })
    except Exception as e:
        print(f'Supplement failed: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({
            'updates': [],
            'reply': '好的，我记下了。还有其他想补充的吗？没问题的话，点击下方的「确认纪要 →」进入下一步。'
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
