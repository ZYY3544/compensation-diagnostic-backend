import os
import requests

def call_openrouter(messages, model=None, temperature=0.3):
    """Convenience function for OpenRouter API calls"""
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        raise ValueError('OPENROUTER_API_KEY not set')

    response = requests.post(
        'https://openrouter.ai/api/v1/chat/completions',
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        json={
            'model': model or os.getenv('OPENROUTER_MODEL', 'openai/gpt-5.4-mini'),
            'messages': messages,
            'temperature': temperature,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content']
