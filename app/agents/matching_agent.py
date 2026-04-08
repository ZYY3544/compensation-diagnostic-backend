import json
from app.agents.base_agent import BaseAgent


class MatchingAgent(BaseAgent):
    """Agent for grade and function matching"""

    def __init__(self):
        super().__init__(temperature=0.2)
        self.grade_prompt = self.load_prompt('matching_grade.txt')
        self.function_prompt = self.load_prompt('matching_function.txt')

    def match_grades(self, grade_list, grade_details, preset_mappings=None):
        """Match client grades to standard grades"""
        # Filter out already matched grades
        unmatched = []
        matched = []
        if preset_mappings:
            for g in grade_list:
                if g in preset_mappings:
                    matched.append({
                        "client_grade": g,
                        "standard_grade": preset_mappings[g],
                        "confidence": "high",
                        "reasoning": "预设映射表命中",
                    })
                else:
                    unmatched.append(g)
        else:
            unmatched = grade_list

        if not unmatched:
            return {"grade_mapping": matched}

        # Call LLM for unmatched grades
        unmatched_details = {g: grade_details.get(g, {}) for g in unmatched}

        messages = [
            {"role": "system", "content": self.grade_prompt},
            {"role": "user", "content": f"""请将以下客户职级映射到标准职级：

## 待匹配职级
{json.dumps(unmatched, ensure_ascii=False)}

## 各职级详情（代表岗位和薪酬范围）
{json.dumps(unmatched_details, ensure_ascii=False, indent=2)}
"""},
        ]

        response = self.call_llm(messages)
        try:
            if '```json' in response:
                response = response.split('```json')[1].split('```')[0]
            elif '```' in response:
                response = response.split('```')[1].split('```')[0]
            llm_result = json.loads(response.strip())
            matched.extend(llm_result.get("grade_mapping", []))
        except json.JSONDecodeError:
            pass

        return {"grade_mapping": matched}

    def match_functions(self, job_titles_with_dept):
        """Match client job titles to standard job functions"""
        all_results = []
        batch_size = 20

        for i in range(0, len(job_titles_with_dept), batch_size):
            batch = job_titles_with_dept[i:i + batch_size]

            messages = [
                {"role": "system", "content": self.function_prompt},
                {"role": "user", "content": f"""请将以下岗位匹配到标准职能类别：

## 待匹配岗位
{json.dumps(batch, ensure_ascii=False, indent=2)}
"""},
            ]

            response = self.call_llm(messages)
            try:
                if '```json' in response:
                    response = response.split('```json')[1].split('```')[0]
                elif '```' in response:
                    response = response.split('```')[1].split('```')[0]
                result = json.loads(response.strip())
                all_results.extend(result.get("function_matching", []))
            except json.JSONDecodeError:
                pass

        return {"function_matching": all_results}

    def run(self, grades, job_titles, data_summary):
        """Legacy interface - run both grade and function matching"""
        grade_details = data_summary.get('grade_details', {}) if data_summary else {}
        grade_result = self.match_grades(grades, grade_details)

        # Build job_titles_with_dept from available data
        job_titles_with_dept = []
        for title in job_titles:
            if isinstance(title, dict):
                job_titles_with_dept.append(title)
            else:
                job_titles_with_dept.append({"title": title, "department": ""})

        function_result = self.match_functions(job_titles_with_dept)

        return {
            "grade_mapping": grade_result.get("grade_mapping", []),
            "function_matching": function_result.get("function_matching", []),
        }
