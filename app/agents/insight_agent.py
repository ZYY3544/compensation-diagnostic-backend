import json
from app.agents.base_agent import BaseAgent


class InsightChatAgent(BaseAgent):
    """Agent for generating diagnostic insights and handling report chat"""

    def __init__(self):
        super().__init__(temperature=0.3)
        self.insight_prompt = self.load_prompt('insight_template.txt')
        self.chat_prompt_template = self.load_prompt('chat_system.txt')

    def generate_insight(self, module_name, module_data, interview_notes=None):
        """Generate insight for a specific analysis module"""
        user_content = f"""请为以下分析模块生成诊断洞察：

## 模块名称
{module_name}

## 分析数据
{json.dumps(module_data, ensure_ascii=False, indent=2)}
"""
        if interview_notes:
            user_content += f"""
## 业务访谈纪要
{json.dumps(interview_notes, ensure_ascii=False, indent=2)}
"""

        messages = [
            {"role": "system", "content": self.insight_prompt},
            {"role": "user", "content": user_content},
        ]

        return self.call_llm(messages)

    def generate_all_insights(self, analysis_results, interview_notes=None):
        """Generate insights for all modules"""
        insights = {}
        modules = analysis_results.get('modules', {})

        for module_name, module_data in modules.items():
            insight = self.generate_insight(module_name, module_data, interview_notes)
            insights[module_name] = insight

        return insights

    def generate_summary(self, all_insights, key_findings):
        """Generate overall diagnostic summary"""
        messages = [
            {"role": "system", "content": self.insight_prompt},
            {"role": "user", "content": f"""请基于以下各模块的洞察，生成3-5句话的整体诊断摘要：

## 各模块洞察
{json.dumps(all_insights, ensure_ascii=False, indent=2)}

## 关键发现
{json.dumps(key_findings, ensure_ascii=False, indent=2)}

请直接输出摘要文字。"""},
        ]

        return self.call_llm(messages)

    def chat(self, user_message, report_context, conversation_history=None):
        """Handle user follow-up questions about the report"""
        system_prompt = self.chat_prompt_template.replace(
            '{context}',
            json.dumps(report_context, ensure_ascii=False, indent=2),
        )

        messages = [{"role": "system", "content": system_prompt}]

        if conversation_history:
            for msg in conversation_history[-10:]:
                messages.append({
                    "role": "user" if msg["role"] == "user" else "assistant",
                    "content": msg.get("text", msg.get("content", "")),
                })

        messages.append({"role": "user", "content": user_message})

        return self.call_llm(messages)

    def run(self, analysis_results, interview_notes=None):
        """Legacy interface - generate insights from analysis results"""
        insights = self.generate_all_insights(analysis_results, interview_notes)
        return {
            'insights': insights,
            'recommendations': [],
        }


# Backward-compatible alias
InsightAgent = InsightChatAgent
