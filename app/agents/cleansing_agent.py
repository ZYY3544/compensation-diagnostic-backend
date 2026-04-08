from app.agents.base_agent import BaseAgent

class CleansingAgent(BaseAgent):
    """Agent for data cleansing"""

    def __init__(self):
        super().__init__(temperature=0.1)

    def run(self, column_names, sample_rows, data_summary):
        """Run data cleansing check"""
        # TODO: Replace with actual LLM call
        # For now return mock result
        return self._mock_result()

    def _mock_result(self):
        return {
            'field_mapping': {},
            'corrections': [],
            'data_issues': [],
            'completeness_score': 78,
        }
