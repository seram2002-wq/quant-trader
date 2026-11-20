"""악재 공시 확인 (장 마감 반전 v2의 필터)

data/dart/YYYYMMDD.csv (tools/collect_dart.py가 저장)에서 종목별 악재 공시를 찾는다.
새 공시 받기는 run.py의 DartCheck가 한다 (매수 시간에는 1분마다).

보는 공시
    - 직전 거래일 파일에서 처음 본 시각(collected_at)이 그날 장 마감(평소 15:30) 이후인 공시 (전날 장 마감 뒤 발표)
    - 그 다음 날부터 오늘까지의 파일 전체 (주말·휴일에 처음 본 공시 포함)
    전날 장중 공시는 이미 전날 주가에 반영됐다고 보고 보지 않는다.

제목 비교
    공백, 대괄호 머리말([기재정정] 등), 가운뎃점(ㆍ·)을 지운 뒤 키워드가 들어 있는지 본다.
    자회사·종속회사 공시와 해제 공시(매매거래정지해제 등)는 악재로 보지 않는다.

호재 공시 (good_news, 스윙 후보 1·3에서 쓸 규칙을 미리 고정)
    단일판매·공급계약체결, 자기주식취득결정, 자기주식취득신탁계약체결결정만. 공백과 가운뎃점만 지우고 비교한다.
    정정·변경·해지·취소·철회·중단·종료·완료·결과·이행·처분, 자회사·종속회사가 들어간 제목은 뺀다
    ([기재정정]도 정정으로 빠짐).
"""
import csv
import re
from datetime import datetime, timedelta
from pathlib import Path

from trader.market import hours

DATA =Path(__file__).resolve().parent.parent / 'data'
DART_DIR = DATA / 'dart'
MINUTE_DIR = DATA / 'minute'

BAD_WORDS = {
    '자금 조달·희석': ['유상증자결정', '전환사채권발행결정', '신주인수권부사채권발행결정',
                    '교환사채권발행결정', '감자결정'],
    '신뢰·지배구조': ['횡령', '배임', '불성실공시법인', '상장적격성', '관리종목', '투자주의환기',
                   '매매거래정지', '회생절차', '파산'],
    '실적·계약': ['공급계약해지', '영업정지', '소송등의제기'],
}
NOT_BAD = ['종속회사', '자회사', '해제']                    # 다른 회사 일이거나 악재가 풀린 공시
WATCH_WORDS = ['조회공시요구', '풍문또는보도', '해명']        # 애매한 공시: 거르지 않고 기록만

# 호재 공시 (스윙 후보 1·3용, 2026-11-20 결과를 보기 전에 고정). 제목에서 공백·가운뎃점만 지우고 비교한다.
# 악재와 달리 [기재정정] 같은 머리말을 지우지 않는다: 정정 공시도 아래 제외어로 걸러야 해서
GOOD_WORDS = ['단일판매공급계약체결', '자기주식취득결정', '자기주식취득신탁계약체결결정']
GOOD_EXCLUDE = ['정정', '변경', '해지', '취소', '철회', '중단', '종료', '완료', '결과', '이행', '처분',
                '자회사', '종속회사']                        # 다른 회사 일이라 그 종목의 호재로 보지 않음


def normalize(title):
    t = re.sub(r'\[[^\]]*\]', '', title or '')               # [기재정정] 같은 머리말
    return re.sub(r'[\sㆍ·]', '', t)


def good_news(title):
    """호재 키워드 또는 None. 제외어가 하나라도 있으면 None"""
    t = re.sub(r'[\sㆍ·]', '', title or '')
    if any(w in t for w in GOOD_EXCLUDE):
        return None
    return next((w for w in GOOD_WORDS if w in t), None)


def classify(title):
    """(분류, 키워드) 또는 (None, 애매 키워드) 또는 (None, None)"""
    t = normalize(title)
    if any(w in t for w in NOT_BAD):
        return None, None
    for group, words in BAD_WORDS.items():
        for w in words:
            if w in t:
                return group, w
    for w in WATCH_WORDS:
        if w in t:
            return None, w
    return None, None


def previous_trading_day(today):
    """오늘 전의 마지막 거래일 (date). 분봉이 저장된 날(data/minute/YYYYMMDD에 파일이 있는 날)을 거래일로 본다.

    shortcut: 프로그램을 돌리지 않은 거래일은 휴장일처럼 건너뛰어 그날 장중 공시까지 걸러진다.
    거래소 휴장일 달력을 쓰게 되면 그것으로 바꿀 것. 10일 안에 기록이 없으면 직전 평일.
    """
    for back in range(1, 11):
        d = today - timedelta(days=back)
        folder = MINUTE_DIR / f'{d:%Y%m%d}'
        if folder.is_dir() and any(folder.glob('*.csv')):
            return d
    d = today - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def read(day):
    p = DART_DIR / f'{day:%Y%m%d}.csv'
    if not p.exists():
        return []
    with open(p, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def window(now=None):
    """지금 판단에 쓸 공시 목록과, 장중 기록이 없어 과하게 걸러질 수 있는 날('YYYYMMDD' 또는 '')"""
    now = now or datetime.now()
    today = now.date()
    prev = previous_trading_day(today)
    close = hours(f'{prev:%Y%m%d}')[1]                        # 그날 장 마감 (수능 날 등은 다름)
    cut = f'{prev:%Y-%m-%d} {close // 100:02d}:{close % 100:02d}:00'
    prev_rows = read(prev)
    rows = [r for r in prev_rows if r.get('collected_at', '') >= cut]
    suspect = f'{prev:%Y%m%d}' if prev_rows and len(rows) == len(prev_rows) else ''
    d = prev + timedelta(days=1)
    while d <= today:
        rows += read(d)
        d += timedelta(days=1)
    return rows, suspect


def scan(codes, now=None):
    """(악재 {종목코드: (분류, 키워드, 제목, 처음 본 시각, 주의 문구)}, 애매 {종목코드: (키워드, 제목)})

    애매 목록에는 악재가 있는 종목은 넣지 않는다.
    """
    rows, suspect = window(now)
    bad, watch = {}, {}
    for r in rows:
        code = (r.get('stock_code') or '').strip()
        if code not in codes or code in bad:
            continue
        title = r.get('report_nm', '')
        group, word = classify(title)
        if group:
            note = '전날 장중 공시일 수 있음 (그날 장중 기록 없음)' if suspect and r.get('rcept_dt') == suspect else ''
            bad[code] = (group, word, title, r.get('collected_at', ''), note)
            watch.pop(code, None)
        elif word and code not in watch:
            watch[code] = (word, title)
    return bad, watch
