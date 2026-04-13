import json
from datetime import date, datetime
from app.agents.base_agent import BaseAgent


class _SafeEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return super().default(o)


class CleansingAgent(BaseAgent):
    """Agent for data cleansing - only handles issues that code can't resolve"""

    def __init__(self):
        super().__init__(temperature=0.1)
        self.system_prompt = self.load_prompt('cleansing.txt')

    def run(self, code_check_results: dict) -> dict:
        """
        接收代码层预检结果，对需要AI判断的问题做专业判断。
        只传代码搞不定的问题给LLM，节省token。
        """
        # 组装需要AI判断的问题
        ai_problems = self._extract_ai_problems(code_check_results)

        if not ai_problems['has_problems']:
            return {'judgments': [], 'performance_mapping': None, 'department_merge': {}}

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": json.dumps(ai_problems, ensure_ascii=False, indent=2, cls=_SafeEncoder)},
        ]

        response = self.call_llm(messages)

        try:
            if '```json' in response:
                response = response.split('```json')[1].split('```')[0]
            elif '```' in response:
                response = response.split('```')[1].split('```')[0]
            return json.loads(response.strip())
        except json.JSONDecodeError:
            return {"error": "Failed to parse LLM response", "raw": response}

    def _extract_ai_problems(self, code_results: dict) -> dict:
        """从代码检测结果中提取需要AI判断的问题"""
        problems = {
            'has_problems': False,
            'sample_rows': code_results.get('sample_rows', []),
            'data_summary': code_results.get('data_summary', {}),
        }

        # 规则1: 需要年化判断的行
        if code_results.get('needs_annualize'):
            problems['annualize_candidates'] = code_results['needs_annualize']
            problems['has_problems'] = True

        # 规则2: 月薪异常值需要判断
        if code_results.get('salary_outliers'):
            problems['salary_outliers'] = code_results['salary_outliers']
            problems['has_problems'] = True

        # 规则3: 年终奖异常值需要判断
        if code_results.get('bonus_outliers'):
            problems['bonus_outliers'] = code_results['bonus_outliers']
            problems['has_problems'] = True

        # 规则5: 绩效等级需要标准化（如果有绩效列）
        perf_values = code_results.get('performance_values')
        if perf_values:
            problems['performance_values'] = perf_values
            problems['has_problems'] = True

        # 规则8: 13薪重复疑似
        if code_results.get('possible_13th_overlap'):
            problems['possible_13th_overlap'] = code_results['possible_13th_overlap']
            problems['has_problems'] = True

        # 规则11: 部门名称列表（供归并）
        departments = code_results.get('unique_departments')
        if departments and len(departments) > 1:
            problems['department_names'] = departments
            problems['has_problems'] = True

        return problems
