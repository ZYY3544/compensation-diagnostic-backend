from app.agents.base_agent import BaseAgent

class MatchingAgent(BaseAgent):
    """Agent for grade and function matching"""

    def __init__(self):
        super().__init__(temperature=0.1)

    def run(self, grades, job_titles, data_summary):
        """Run grade and function matching"""
        # TODO: Replace with actual LLM call
        # For now return mock result
        return self._mock_result()

    def _mock_result(self):
        return {
            'grade_mapping': [],
            'function_mapping': [],
        }
