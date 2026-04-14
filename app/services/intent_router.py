"""
意图识别：一次 AI 调用同时完成 skill 分类 + 参数提取。

输入用户消息 → 输出：
{
  'skill': 'external_benchmark' | ... | 'unclear',
  'confidence': 0.0-1.0,
  'params': {'department': ..., 'grade': ..., 'city': ..., 'candidate_ask': ...},
  'method': 'ai' | 'fallback',
  'reason': str,
}

- 不再用 triggers 做关键词匹配；skill 文件里的 triggers 字段仅作文档参考
- confidence < 0.6 或 skill == 'unclear' → 上游应追问用户
- 无 AI key / AI 失败 → fallback 到 general_question，confidence=0
"""
import os
import json
from app.skills import get_registry


def classify_intent(message: str, context: dict = None) -> dict:
    message = (message or '').strip()
    if not message:
        return {
            'skill': 'unclear', 'confidence': 0.0, 'params': {},
            'method': 'none', 'reason': 'empty message',
        }

    registry = get_registry()

    # 没 AI key 时只能走 general_question fallback
    if not os.getenv('OPENROUTER_API_KEY', '').strip():
        return {
            'skill': 'general_question', 'confidence': 0.0, 'params': {},
            'method': 'fallback', 'reason': '未配置 OPENROUTER_API_KEY，直接走通用问答',
        }

    return _classify_by_ai(message, registry, context or {})


def _classify_by_ai(message: str, registry, context: dict) -> dict:
    """单次 AI 调用：同时做意图分类 + 参数提取。"""
    try:
        from app.agents.base_agent import BaseAgent
        agent = BaseAgent(temperature=0.1)

        skills = registry.list_all()
        skills_desc = '\n'.join(
            f'- {s["key"]}: {s["display_name"]}'
            + (f' —— {s["description"]}' if s.get('description') else '')
            for s in skills
        )

        system = (
            "你是铭曦薪酬诊断产品的意图识别器。"
            "根据用户的消息，判断最匹配的能力，并提取相关参数。"
            "只输出 JSON，不要其他内容。"
        )
        user_prompt = f"""用户消息：「{message}」

可用能力：
{skills_desc}

输出 JSON：
{{
  "skill": "能力key 或 'unclear'",
  "confidence": 0.0-1.0,
  "params": {{
    "department": "提取到的部门，没有则 null",
    "grade": "提取到的职级，没有则 null",
    "city": "提取到的城市，没有则 null",
    "candidate_ask": "提取到的金额（纯数字），没有则 null"
  }}
}}

规则：
- 如果是闲聊或解释概念类的通用问题，选 general_question
- 如果完全不相关或信息严重不足，skill 设为 "unclear"，confidence=0
- confidence 反映对意图判断的把握：0.9+ 非常确定 / 0.6-0.9 较确定 / <0.6 不确定"""

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ]
        response = agent.call_llm(messages)

        # 剥 code fence
        if '```json' in response:
            response = response.split('```json')[1].split('```')[0]
        elif '```' in response:
            response = response.split('```')[1].split('```')[0]

        parsed = json.loads(response.strip())
        skill_key = parsed.get('skill', 'unclear')
        confidence = float(parsed.get('confidence', 0.0))
        raw_params = parsed.get('params') or {}

        # 规范化 params：剔掉 null/空字符串
        params = {}
        for k, v in raw_params.items():
            if v is None or v == '' or v == 'null':
                continue
            params[k] = v
        # candidate_ask 归一化成 int
        if 'candidate_ask' in params:
            try:
                params['candidate_ask'] = int(float(str(params['candidate_ask']).replace(',', '')))
            except Exception:
                params.pop('candidate_ask', None)

        # 兜底：AI 返回的 skill 不在注册表里 → unclear
        if skill_key != 'unclear' and not registry.get(skill_key):
            return {
                'skill': 'unclear', 'confidence': 0.0, 'params': params,
                'method': 'ai', 'reason': f'AI 返回了未知 skill: {skill_key}',
            }

        return {
            'skill': skill_key, 'confidence': confidence, 'params': params,
            'method': 'ai',
            'reason': parsed.get('reason') or f'AI 判断 (confidence {confidence:.2f})',
        }

    except Exception as e:
        print(f'[IntentRouter] AI classification failed: {e}')
        return {
            'skill': 'general_question', 'confidence': 0.0, 'params': {},
            'method': 'fallback', 'reason': f'AI 失败 fallback: {e}',
        }
