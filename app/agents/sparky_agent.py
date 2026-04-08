from app.agents.base_agent import BaseAgent

class SparkyAgent(BaseAgent):
    """Agent for Sparky conversational interface"""

    def __init__(self):
        super().__init__(temperature=0.5)

    def run(self, message, session_context, stage='chat'):
        """Generate Sparky response"""
        # TODO: Replace with actual LLM call
        # For now return mock result
        return self._mock_result(message)

    def _mock_result(self, message):
        return {
            'response': f'收到你的问题：{message}。这是一个 mock 回复。',
        }
