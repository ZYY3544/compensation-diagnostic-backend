"""
意图识别：关键词规则优先 + AI 兜底。
输入用户消息 → 输出 skill_key 或 'unknown'/'clarify'。
"""
import os
import re
import json
from app.services.skill_registry import SKILLS, get_skill


def classify_intent(message: str, context: dict = None) -> dict:
    """
    返回 {
        'skill': 'external_benchmark' | None,
        'confidence': 'high' | 'medium' | 'low',
        'method': 'keyword' | 'ai' | 'none',
        'reason': str,
    }
    """
    message = message.strip()
    if not message:
        return {'skill': None, 'confidence': 'low', 'method': 'none', 'reason': 'empty message'}

    # Step 1: 关键词匹配
    kw_result = _classify_by_keywords(message)
    if kw_result['confidence'] == 'high':
        return kw_result

    # Step 2: AI 兜底
    if os.getenv('OPENROUTER_API_KEY', '').strip():
        ai_result = _classify_by_ai(message, context or {})
        if ai_result['skill']:
            return ai_result

    # Step 3: 都匹配不到
    if kw_result['skill']:
        return kw_result  # 关键词有低置信度结果
    return {'skill': None, 'confidence': 'low', 'method': 'none', 'reason': '无法识别意图'}


def _classify_by_keywords(message: str) -> dict:
    """关键词匹配。统计每个 skill 命中多少关键词，得分最高的胜出。"""
    scores: dict[str, int] = {}
    hits: dict[str, list[str]] = {}
    for skill_key, skill in SKILLS.items():
        for trigger in skill.get('triggers', []):
            if trigger.lower() in message.lower():
                scores[skill_key] = scores.get(skill_key, 0) + 1
                hits.setdefault(skill_key, []).append(trigger)

    if not scores:
        return {'skill': None, 'confidence': 'low', 'method': 'keyword', 'reason': '无关键词命中'}

    # 最高分
    best_key = max(scores, key=scores.get)
    best_score = scores[best_key]
    # 多个 skill 并列时降级为 medium
    tied = [k for k, v in scores.items() if v == best_score]
    confidence = 'high' if len(tied) == 1 and best_score >= 1 else 'medium'

    return {
        'skill': best_key,
        'confidence': confidence,
        'method': 'keyword',
        'reason': f'命中关键词: {", ".join(hits[best_key])}',
    }


def _classify_by_ai(message: str, context: dict) -> dict:
    """AI 兜底：关键词识别不确定时交给 LLM。"""
    try:
        from app.agents.base_agent import BaseAgent
        agent = BaseAgent(temperature=0.1)

        skills_desc = '\n'.join(
            f'- {s["key"]}: {s["display_name"]}（{"重模式" if s["mode"]=="heavy" else "轻模式"}）'
            for s in SKILLS.values()
        )

        prompt = f"""用户发消息：「{message}」

请判断用户想做什么，从以下能力中选一个：
{skills_desc}

如果消息是闲聊或无法归类，返回 null。
只输出 JSON：{{"skill": "能力key或null", "reason": "简短理由"}}"""

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
        if skill_key and skill_key != 'null' and get_skill(skill_key):
            return {
                'skill': skill_key,
                'confidence': 'medium',
                'method': 'ai',
                'reason': result.get('reason', 'AI 判断'),
            }
    except Exception as e:
        print(f'[IntentRouter] AI classification failed: {e}')

    return {'skill': None, 'confidence': 'low', 'method': 'ai', 'reason': 'AI 未识别'}
