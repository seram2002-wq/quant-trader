"""한국거래소 로그인 확인 (비밀번호는 출력하지 않음)

    python tools/krx_login_check.py
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env', override=True)
uid, pw = os.getenv('KRX_ID') or '', os.getenv('KRX_PW') or ''
QUOTES = ('"', "'")
print(f'KRX_ID 길이 {len(uid)}, 앞뒤 공백 {uid != uid.strip()}, 따옴표로 시작 {uid[:1] in QUOTES}')
print(f'KRX_PW 길이 {len(pw)}, 앞뒤 공백 {pw != pw.strip()}, 따옴표로 시작 {pw[:1] in QUOTES}')
if not (uid and pw):
    sys.exit('.env에서 KRX_ID 또는 KRX_PW를 찾지 못했습니다.')

import requests                                   # noqa: E402
from pykrx.website.comm import auth              # noqa: E402

s = requests.Session()
auth.warmup_krx_session(s)
payload = {'mbrNm': '', 'telNo': '', 'di': '', 'certType': '', 'mbrId': uid, 'pw': pw}
headers = {'User-Agent': auth.USER_AGENT, 'Referer': auth.LOGIN_PAGE}
for skip in ('', 'Y'):
    if skip:
        payload['skipDup'] = 'Y'
    res = s.post(auth.LOGIN_URL, data=payload, headers=headers, timeout=15)
    try:
        data = res.json()
    except ValueError:
        sys.exit(f'응답을 해석할 수 없습니다 (HTTP {res.status_code})')
    code, msg = data.get('_error_code', ''), data.get('_error_message', '')
    print(f'거래소 응답 : {code} {msg}')
    if code != 'CD011':
        break
print('로그인 성공' if code == 'CD001' else '로그인 실패')
