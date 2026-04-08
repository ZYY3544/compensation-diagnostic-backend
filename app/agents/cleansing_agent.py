import json
from app.agents.base_agent import BaseAgent


class CleansingAgent(BaseAgent):
    """Agent for data cleansing"""

    def __init__(self):
        super().__init__(temperature=0.1)
        self.system_prompt = self.load_prompt('cleansing.txt')

    def run(self, column_names, sample_rows, data_summary, suspicious_rows=None):
        """Run data cleansing check via LLM"""
        user_content = f"""以下是客户上传的薪酬数据信息：

## 列名
{json.dumps(column_names, ensure_ascii=False)}

## 前5行样本数据
{json.dumps(sample_rows, ensure_ascii=False, indent=2)}

## 每列统计摘要
{json.dumps(data_summary, ensure_ascii=False, indent=2)}
"""
        if suspicious_rows:
            user_content += f"""
## 代码预筛的疑似问题行
{json.dumps(suspicious_rows, ensure_ascii=False, indent=2)}
"""

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]

        response = self.call_llm(messages)

        # Parse JSON from response
        try:
            if '```json' in response:
                response = response.split('```json')[1].split('```')[0]
            elif '```' in response:
                response = response.split('```')[1].split('```')[0]
            return json.loads(response.strip())
        except json.JSONDecodeError:
            return {"error": "Failed to parse LLM response", "raw": response}
