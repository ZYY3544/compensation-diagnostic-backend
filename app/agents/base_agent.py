import os
import requests

class BaseAgent:
    """Base class for all LLM agents"""

    def __init__(self, temperature=0.3, model=None):
        self.api_key = os.getenv('OPENROUTER_API_KEY', '')
        self.model = model or os.getenv('OPENROUTER_MODEL', 'openai/gpt-5.4-mini')
        self.temperature = temperature
        self.base_url = 'https://openrouter.ai/api/v1/chat/completions'

    def call_llm(self, messages, **kwargs):
        """Call OpenRouter API"""
        if not self.api_key:
            raise ValueError('OPENROUTER_API_KEY not set')

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

        payload = {
            'model': self.model,
            'messages': messages,
            'temperature': kwargs.get('temperature', self.temperature),
        }

        response = requests.post(self.base_url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        result = response.json()
        return result['choices'][0]['message']['content']

    def load_prompt(self, prompt_name):
        """Load prompt template from prompts/ directory"""
        prompt_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'prompts', prompt_name)
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
