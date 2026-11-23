"""뉴스 판정 그림자 기록 (매매에는 쓰지 않고 data/news/YYYYMMDD.csv에 쌓기만 한다)

네이버 뉴스 검색 API(네이버 클라우드 NAVER API HUB, .env의 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET)로 종목명을 최신순 검색하고,
기사 제목을 규칙 사전으로 판정해 저장한다. 언제 어떤 종목을 볼지는 run.py의 NewsCheck가 정한다.

판정 (제목만, 공백을 지우고 비교)
    악재  : 악재 키워드가 있고 예외어가 없음
    예외  : 악재 키워드가 있지만 예외어(무혐의·해제·기각 등)도 있음 → 악재로 보지 않음
    호재  : 호재 키워드만 있음
    혼재  : 악재(예외 아님)와 호재가 같이 있음
    중립  : 아무것도 없음
    "공급계약해지"처럼 악재 키워드 안에 호재 키워드가 겹치면 악재만 센다.

저장하는 기사
    직전 거래일 장 마감 뒤에 나온 기사만 (그 전 기사는 이미 주가에 반영됐다고 봄)
    (종목, 링크)가 같은 기사는 한 번만. 프로그램을 다시 켜도 오늘 파일에서 읽어 이어 간다
    기사 시각(pub_time)도 저장해 두어, 나중에 백테스트할 때 그 시각 이후에만 안 것으로 처리할 수 있다

한계: 종목명으로 검색하므로 이름이 흔한 낱말인 종목(예: 대상)은 다른 기사가 섞인다. 판정 결과는 거래와 비교해 본 뒤 쓸 것.
"""
import csv
import html
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from trader.disclosures import previous_trading_day
from trader.market import hours

API_URL = 'https://naverapihub.apigw.ntruss.com/search/v1/news'   # NAVER API HUB (옛 openapi.naver.com은 2026-06 이전)
NEWS_DIR = Path(__file__).resolve().parent.parent / 'data' / 'news'
FIELDS = ['time', 'code', 'name', 'verdict', 'keywords', 'title', 'link', 'pub_time']

BAD = ['압수수색', '횡령', '배임', '분식회계', '상장폐지', '거래정지', '유상증자', '리콜', '화재', '가동중단',
       '계약해지', '어닝쇼크', '적자전환', '부도', '파산', '회생절차', '의견거절']
EXCEPT = ['무혐의', '무죄', '해제', '해소', '재개', '기각', '철회', '반박', '사실무근']
GOOD = ['수주', '공급계약', '역대최대', '최대실적', '어닝서프라이즈', '흑자전환', '자사주소각', '자사주매입']


def clean(text):
    """네이버가 붙인 <b> 태그와 &quot; 같은 문자를 지운다"""
    return html.unescape(re.sub(r'<[^>]+>', '', text or '')).strip()


def judge(title):
    """(판정, [맞은 키워드])"""
    t = re.sub(r'\s', '', title)
    bad = [w for w in BAD if w in t]
    exc = [w for w in EXCEPT if w in t]
    rest = t
    for w in bad:
        rest = rest.replace(w, ' ')                     # 공급계약해지 → 호재 '공급계약'으로 다시 세지 않게
    good = [w for w in GOOD if w in rest]
    if bad and not exc:
        verdict = '혼재' if good else '악재'
    elif good:
        verdict = '호재'
    else:
        verdict = '예외' if bad else '중립'
    return verdict, bad + exc + good


def path_of(day):
    return NEWS_DIR / f'{day}.csv'


def load_seen(day):
    p = path_of(day)
    if not p.exists():
        return set()
    with open(p, encoding='utf-8-sig', newline='') as f:
        return {(r['code'], r['link']) for r in csv.DictReader(f)}


def since_prev_close(now):
    prev = previous_trading_day(now.date())
    close = hours(f'{prev:%Y%m%d}')[1]
    return datetime(prev.year, prev.month, prev.day, close // 100, close % 100)


def check(codes, client_id, secret, seen, now=None, log=print):
    """codes {종목코드: 종목명}의 새 기사를 판정해 오늘 파일에 더한다. 저장한 건수를 돌려준다

    seen: 이미 본 (종목코드, 링크) 집합. 이 함수가 채운다
    """
    now = now or datetime.now()
    since = since_prev_close(now)
    rows = []
    for code, name in codes.items():
        try:
            res = requests.get(API_URL, timeout=5, params={'query': name, 'display': 20, 'sort': 'date'},
                               headers={'X-NCP-APIGW-API-KEY-ID': client_id, 'X-NCP-APIGW-API-KEY': secret})
        except requests.RequestException as ex:
            log(f'뉴스 검색 실패 {name}({code}) : {ex}')
            continue
        if res.status_code != 200:                      # 키 오류·한도 초과: 이번 바퀴는 그만
            log(f'뉴스 검색 응답 {res.status_code} : {res.text[:100]}')
            break
        try:
            items = res.json().get('items') or []
        except ValueError:
            log(f'뉴스 검색 응답을 읽지 못함 {name}({code})')
            continue
        for item in items:
            link = item.get('originallink') or item.get('link') or ''
            try:
                pub = parsedate_to_datetime(item.get('pubDate', '')).astimezone().replace(tzinfo=None)
            except (TypeError, ValueError):
                continue
            if pub < since or (code, link) in seen:
                continue
            seen.add((code, link))
            title = clean(item.get('title'))
            verdict, words = judge(title)
            rows.append({'time': now.strftime('%Y-%m-%d %H:%M:%S'), 'code': code, 'name': name,
                         'verdict': verdict, 'keywords': ' '.join(words), 'title': title, 'link': link,
                         'pub_time': pub.strftime('%Y-%m-%d %H:%M:%S')})
    if rows:
        p = path_of(now.strftime('%Y%m%d'))
        p.parent.mkdir(parents=True, exist_ok=True)
        new = not p.exists()
        with open(p, 'a', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerows(rows)
    return len(rows)
