"""
意图识别：关键词规则优先 + AI 兜底 + 无法识别时返回 general_question 兜底。
输入用户消息 → 输出 skill_key。
用法：
    result = classify_intent(user_message, context={'has_data': True, ...})
"""
import os
import json
from app.skills import get_registry


def classify_intent(message: str, context: dict = None) -> dict:
    """
    返回 {
        'skill': 'external_benchmark',
        'confidence': 'high' | 'medium' | 'low',
        'method': 'keyword' | 'ai' | 'fallback',
        'reason': str,
    }
    """
    message = (message or '').strip()
    if not message:
        return {'skill': None, 'confidence': 'low', 'method': 'none', 'reason': 'empty message'}

    registry = get_registry()

    # Step 1: 关键词匹配
    matched = registry.match_by_keyword(message)
    if matched:
        return {
            'skill': matched,
            'confidence': 'high',
            'method': 'keyword',
            'reason': f'关键词命中 {matched}',
        }

    # Step 2: AI 兜底分类
    if os.getenv('OPENROUTER_API_KEY', '').strip():
        ai_result = _classify_by_ai(message, registry, context or {})
        if ai_result['skill']:
            return ai_result

    # Step 3: 兜底到 general_question（知识问答）
    return {
        'skill': 'general_question',
        'confidence': 'low',
        'method': 'fallback',
        'reason': '无法精确识别意图，走知识问答兜底',
    }


def _classify_by_ai(message: str, registry, context: dict) -> dict:
    """AI 兜底：关键词识别不到时交给 LLM。"""
    try:
        from app.agents.base_agent import BaseAgent
        agent = BaseAgent(temperature=0.1)

        skills = registry.list_all()
        skills_desc = '\n'.join(
            f'- {s["key"]}: {s["display_name"]}（{"重模式" if s["mode"]=="heavy" else "轻模式"}）'
            for s in skills
        )

        prompt = f"""用户发消息：「{message}」

请判断用户想做什么，从以下能力中选一个：
{skills_desc}

如果是闲聊或解释概念类，返回 general_question。
只输出 JSON：{{"skill": "能力key", "reason": "简短理由"}}"""

        messages = [
            {"role": "system", "content": "你是铭曦系统的意图识别模块。只输出 JSON。"},
            {"role": "user", "content": prompt},
        ]
        response = agent.call_llm(messages)

        if '```json' in response:
            response = response.split('```json')[1].split('```')[0]
        elif '```' in response:
            response = response.split('```')[1].split('```')[0]

        result = json.loads(response.strip())
        skill_key = result.get('skill')
        if skill_key and registry.get(skill_key):
            return {
                'skill': skill_key,
                'confidence': 'medium',
                'method': 'ai',
                'reason': result.get('reason', 'AI 判断'),
            }
    except Exception as e:
        print(f'[IntentRouter] AI classification failed: {e}')

    return {'skill': None, 'confidence': 'low', 'method': 'ai', 'reason': 'AI 未识别'}
