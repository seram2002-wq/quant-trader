"""GPT로 후보 수식 N개 받기 (OpenAI Chat Completions, JSON 스키마로 형식 고정)

.env: OPENAI_API_KEY (필수), OPENAI_MODEL (없으면 DEFAULT_MODEL). 키는 로그에 남기지 않는다.
새 패키지 없이 requests로 직접 부른다.
"""
import json
import os
import time

import requests

API_URL = 'https://api.openai.com/v1/chat/completions'
DEFAULT_MODEL = 'gpt-4.1'
SCHEMA = {
    'type': 'object',
    'properties': {'formulas': {'type': 'array', 'items': {
        'type': 'object',
        'properties': {'formula': {'type': 'string'}, 'idea': {'type': 'string'}},
        'required': ['formula', 'idea'], 'additionalProperties': False}}},
    'required': ['formulas'], 'additionalProperties': False,
}


class LLMError(Exception):
    pass


def propose(system, user, model=None, tries=3):
    """[{'formula', 'idea'}]. 429·5xx·연결 오류는 잠시 뒤 다시 시도"""
    key = os.getenv('OPENAI_API_KEY', '').strip()
    if not key:
        raise LLMError('.env에 OPENAI_API_KEY가 없습니다')
    body = {'model': model or os.getenv('OPENAI_MODEL', '').strip() or DEFAULT_MODEL,
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
            'response_format': {'type': 'json_schema',
                                'json_schema': {'name': 'alpha_formulas', 'strict': True, 'schema': SCHEMA}}}
    for attempt in range(1, tries + 1):
        try:
            res = requests.post(API_URL, json=body, timeout=180, headers={'Authorization': f'Bearer {key}'})
        except requests.RequestException as ex:
            err = f'연결 오류: {ex}'
        else:
            if res.status_code == 200:
                msg = res.json()['choices'][0]['message']
                if msg.get('refusal'):
                    raise LLMError(f"모델이 거절했습니다: {msg['refusal']}")
                return json.loads(msg['content'])['formulas']
            err = f'HTTP {res.status_code}: {res.text[:200]}'
            if res.status_code not in (429, 500, 502, 503, 504):
                raise LLMError(err)
        if attempt < tries:
            time.sleep(10 * attempt)
    raise LLMError(err)
