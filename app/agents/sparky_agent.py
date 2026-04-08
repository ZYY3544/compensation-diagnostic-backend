import json
from app.agents.base_agent import BaseAgent


class SparkyAgent(BaseAgent):
    """Agent for Sparky conversational interface"""

    def __init__(self):
        super().__init__(temperature=0.5)
        self.system_prompt = self.load_prompt('sparky.txt')

    def chat(self, user_message, context=None, conversation_history=None):
        """Generate Sparky's response"""
        messages = [{"role": "system", "content": self.system_prompt}]

        if context:
            messages.append({
                "role": "system",
                "content": f"当前诊断上下文信息：\n{json.dumps(context, ensure_ascii=False, indent=2)}",
            })

        if conversation_history:
            for msg in conversation_history[-10:]:  # Keep last 10 messages
                messages.append({
                    "role": "user" if msg["role"] == "user" else "assistant",
                    "content": msg["text"] if "text" in msg else msg.get("content", ""),
                })

        messages.append({"role": "user", "content": user_message})

        return self.call_llm(messages)

    def generate_interview_questions(self, data_summary=None):
        """Generate business interview questions based on data"""
        prompt = """基于以下数据概况，生成5-6个业务访谈问题，用于了解客户的业务背景。

问题应该覆盖：
1. 诊断诉求（留人/招人/控成本/公平性）
2. 薪酬策略现状（市场定位、调薪机制）
3. 组织背景（核心职能、人才流失、战略方向）

以JSON数组格式输出，每个问题包含 question 和 context 字段。"""

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]

        if data_summary:
            messages[1]["content"] += f"\n\n数据概况：\n{json.dumps(data_summary, ensure_ascii=False)}"

        response = self.call_llm(messages)
        try:
            if '```json' in response:
                response = response.split('```json')[1].split('```')[0]
            elif '```' in response:
                response = response.split('```')[1].split('```')[0]
            return json.loads(response.strip())
        except json.JSONDecodeError:
            return []

    def run(self, message, session_context=None, stage='chat'):
        """Legacy interface - generate Sparky response"""
        return {
            'response': self.chat(message, context=session_context),
        }
