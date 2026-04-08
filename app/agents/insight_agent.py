from app.agents.base_agent import BaseAgent

class InsightAgent(BaseAgent):
    """Agent for generating diagnostic insights"""

    def __init__(self):
        super().__init__(temperature=0.3)

    def run(self, analysis_results, interview_notes=None):
        """Generate insights from analysis results"""
        # TODO: Replace with actual LLM call
        # For now return mock result
        return self._mock_result()

    def _mock_result(self):
        return {
            'insights': [],
            'recommendations': [],
        }
