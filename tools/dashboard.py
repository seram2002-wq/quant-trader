"""지난 날 다시 보기 웹 전광판: 장부별 하루 손익 곡선, 1분봉 차트 위 매매 지점, v3 판단

    python -m tools.dashboard          http://localhost:8642 을 연다

탭: 나(이 PC의 data/), 팀원(.env의 TEAM_DIR 공유 폴더, tools/team_export.py가 내보낸 것), 주간 랭킹(모의 장부만)

data/ 파일만 읽는다 (한국투자 API를 부르지 않아 run.py 매매와 상관없음). 이 PC에서만 열린다.
손익은 장부 기록 기준: 실현 손익 + 들고 있는 종목의 (그 분 종가 × 수량 - 매수 금액).
전날부터 들고 온 종목은 매입가 기준이라 밤사이 움직임도 들어간다 (슬랙 잔고판의 '오늘'과 같은 기준).
"""
import json
import os
import sys
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv                       # noqa: E402

load_dotenv(ROOT / '.env', override=True)

import config                                        # noqa: E402
from tools.team_export import books as list_books    # noqa: E402
from trader.paper_broker import TRADE_FIELDS         # noqa: E402

DATA = ROOT / 'data'
PAGE = Path(__file__).with_name('dashboard.html')
INDEX = '069500'                                     # KODEX 200
TEAM = Path(os.getenv('TEAM_DIR', '').strip() or ROOT / 'no_team')   # 구글 드라이브 공유 폴더 (tools/team_export.py)
ME = os.getenv('TEAM_NAME', '').strip() or '나'


def source(person):
    """(자료 폴더, [(장부, 이름, 자금, 계좌)]). 나는 이 PC의 data/, 팀원은 공유 폴더의 그 사람 폴더"""
    if person in ('', ME):
        bs = list_books(config.STRATEGIES)
        return DATA, [(b['book'], b['label'], b['capital'], b['account']) for b in bs]
    root = TEAM / person
    bs = json.loads((root / 'books.json').read_text(encoding='utf-8'))
    return root, [(b['book'], b['label'], b['capital'], b['account']) for b in bs]


def people():
    """공유 폴더에서 장부를 내보낸 사람들 (나 포함)"""
    return sorted(p.name for p in TEAM.iterdir() if (p / 'books.json').exists()) if TEAM.is_dir() else []


def bars(day, code, root=DATA):
    path = root / 'minute' / day / f'{code}.csv'
    if not path.exists():
        path = DATA / 'minute' / day / f'{code}.csv'      # 팀원이 안 보낸 분봉은 이 PC에 있으면 그것으로
    if not path.exists():
        return None
    b = pd.read_csv(path, dtype={'time': str})
    b['hhmm'] = b['time'].str[:4]
    return b


def trades(book, root=DATA):
    path = root / book / 'trades.csv'
    if not path.exists():                            # 아직 매매가 없는 장부 (팀원 모멘텀 장부 등)
        return pd.DataFrame(columns=TRADE_FIELDS + ['day', 'hhmm'])
    # 예전 장부는 머리줄에 version 칸이 없어서 칸 이름을 직접 준다
    t = pd.read_csv(path, dtype={'code': str}, names=TRADE_FIELDS, skiprows=1, encoding='utf-8-sig')
    t['day'] = t['time'].str[:10].str.replace('-', '')
    t['hhmm'] = t['time'].str[11:16].str.replace(':', '')
    return t


def day_pnl(t, day, closes):
    """[(hhmm, 손익 원)] 분마다. t: 장부 매매 기록, closes: {code: Series(hhmm → 종가)}"""
    held = {}
    for r in t[t['day'] < day].itertuples():       # 오늘 시작할 때 들고 있던 종목
        if r.side == 'BUY':
            held[r.code] = (r.qty, r.amount + r.fee)
        else:
            held.pop(r.code, None)
    today = t[t['day'] == day]
    minutes = sorted({m for c in closes.values() for m in c.index}) or sorted(set(today['hhmm']))  # 분봉 없는 날은 매매 시각만
    out, realized, i, rows = [], 0.0, 0, list(today.itertuples())
    for m in minutes:
        while i < len(rows) and rows[i].hhmm <= m:
            r = rows[i]
            if r.side == 'BUY':
                held[r.code] = (r.qty, r.amount + r.fee)
            else:
                held.pop(r.code, None)
                realized += float(r.profit)
            i += 1
        value = 0.0
        for code, (qty, cost) in held.items():
            c = closes.get(code)
            px = c[c.index <= m] if c is not None else None
            value += qty * px.iloc[-1] - cost if px is not None and len(px) else 0.0   # 시세 없으면 매입가로
        out.append((m, round(realized + value)))
    return out


def day_data(day, person=''):
    out = {'books': [], 'trades': [], 'stocks': {}, 'v3': [], 'report': []}
    root, bs = source(person)
    logs = [(b, label, cap, trades(b, root)) for b, label, cap, _ in bs]
    codes = {INDEX} | {c for *_, t in logs for c in t.loc[t['day'] <= day, 'code']}
    closes = {}
    for c in codes:
        b = bars(day, c, root)
        if b is not None:
            closes[c] = b.set_index('hhmm')['close']
    for b, label, cap, t in logs:
        curve = day_pnl(t, day, closes)
        out['books'].append({'label': label, 'curve': [(m, v / cap * 100) for m, v in curve],
                             'pnl': curve[-1][1] if curve else 0})
        for r in t[t['day'] == day].itertuples():
            out['trades'].append({'book': label, 'side': r.side, 'code': r.code, 'name': r.name, 'hhmm': r.hhmm,
                                  'qty': int(r.qty), 'price': float(r.price),
                                  'profit': None if pd.isna(r.profit) else float(r.profit)})
            out['stocks'][r.code] = r.name
    if INDEX in closes:
        k = closes[INDEX]
        out['index'] = [(m, (v / k.iloc[0] - 1) * 100) for m, v in k.items()]
    try:                                             # v3 판단: 내 것은 이 PC에서 계산, 팀원 것은 공유 폴더의 v3/<날짜>.csv
        table = None
        if root == DATA:
            from tools import v3_report
            res = v3_report.analyze(day)
            if res is not None:
                d = pd.read_csv(DATA / 'paper_close_reversal_v3' / 'decisions' / f'{day}.csv', dtype={'code': str})
                peers = d.groupby('code')['peers'].last().fillna('')
                table = res[0].assign(peers=lambda x: x['code'].map(peers))
        elif (root / 'v3' / f'{day}.csv').exists():
            table = pd.read_csv(root / 'v3' / f'{day}.csv', dtype={'code': str, 'peers': str}).fillna({'peers': ''})
        if table is not None:
            table = table.astype(object)
            out['v3'] = table.where(table.notna(), None).to_dict('records')
            for r in out['v3']:
                out['stocks'].setdefault(r['code'], r['name'])
            from trader import basket
            b = basket.load(day)
            out['names'] = {} if b is None else dict(zip(b['code'], b['name']))    # 업종 동료 이름
    except Exception as ex:                          # v3 기록이 없거나 깨진 날도 나머지는 보이게
        out['v3_error'] = str(ex)
    path = DATA / 'paper_close_reversal_v3' / 'report.csv' if root == DATA else root / 'v3_effect.csv'
    if path.exists():
        r = pd.read_csv(path, dtype={'day': str})[['day', 'filter_effect', 'range_effect']].astype(object)
        out['report'] = r.where(r.notna(), None).to_dict('records')       # NaN은 JSON에 못 넣음
    return out


def lines(day, codes):
    """{code: [(hhmm, 시가 대비 %)]} 업종 동료와 겹쳐 보기용"""
    out = {}
    for c in codes:
        b = bars(day, c)
        if b is not None:
            out[c] = [(m, (v / b['open'].iloc[0] - 1) * 100) for m, v in zip(b['hhmm'], b['close'])]
    return out


def days_of(person=''):
    """그 사람의 분봉이나 매매가 있는 날 (최근 날짜부터)"""
    root, bs = source(person)
    days = {p.name for p in (root / 'minute').iterdir() if p.name.isdigit()} if (root / 'minute').is_dir() else set()
    for b, *_ in bs:
        days |= set(trades(b, root)['day'].dropna())
        if (root / b / 'equity.csv').exists():          # 매매 없는 날도 장 마감 총자산이 있으면 탭에 보이게
            days |= set(pd.read_csv(root / b / 'equity.csv', dtype={'day': str})['day'])
    return sorted(days, reverse=True)


def monday(day):
    d = datetime.strptime(day, '%Y%m%d')
    return (d - timedelta(days=d.weekday())).strftime('%Y%m%d')


def week_rows(entries, week=None):
    """entries: [(사람, 장부 이름, 자금, 총자산 표(day, equity), 매매 기록)]. 그 주(월요일 YYYYMMDD) 순위
    주간 수익률 = 그 주 마지막 날 총자산 ÷ 지난주 마지막 날 총자산 - 1 (지난주 기록이 없으면 자금 기준)"""
    weeks = sorted({monday(d) for *_, eq, _ in entries for d in eq['day']}, reverse=True)
    if not weeks:
        return {'weeks': [], 'week': None, 'rows': []}
    week = week if week in weeks else weeks[0]
    end = (datetime.strptime(week, '%Y%m%d') + timedelta(days=7)).strftime('%Y%m%d')
    rows = []
    for person, label, cap, eq, t in entries:
        now = eq[(eq['day'] >= week) & (eq['day'] < end)]
        if now.empty:
            continue
        before = eq[eq['day'] < week]
        base = float(before['equity'].iloc[-1]) if len(before) else float(cap)
        sells = pd.to_numeric(t.loc[(t['side'] == 'SELL') & (t['day'] >= week) & (t['day'] < end), 'profit'])
        last = float(now['equity'].iloc[-1])
        rows.append({'person': person, 'label': label, 'ret': (last / base - 1) * 100, 'pnl': last - base,
                     'sells': len(sells), 'win': float((sells > 0).mean()) * 100 if len(sells) else None,
                     'worst': float(sells.min()) if len(sells) else None,
                     'curve': [(d, (e / base - 1) * 100) for d, e in zip(now['day'], now['equity'])]})
    rows.sort(key=lambda r: -r['ret'])
    return {'weeks': weeks, 'week': week, 'rows': rows}


def ranking(week=None):
    """주간 랭킹: 공유 폴더의 모든 사람(나 포함)의 모의 장부"""
    entries = []
    for person in people():                          # 내 것도 공유 폴더에 내보낸 기록으로 (팀원과 같은 기준)
        root = TEAM / person
        for b in json.loads((root / 'books.json').read_text(encoding='utf-8')):
            book, label, cap = b['book'], b['label'], b['capital']
            path = root / book / 'equity.csv'
            if b['account'] == 'mock' and path.exists():
                eq = pd.read_csv(path, dtype={'day': str})
                entries.append((person, label, cap, eq, trades(book, root)))
    return week_rows(entries, week)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        day, code, person = q.get('d', ''), q.get('code', ''), q.get('p', '')
        if person not in ('', ME) and person not in people():      # 공유 폴더 밖 경로를 못 읽게
            return self.send(400, {'error': '없는 사람'})
        if not (day.isdigit() and len(day) == 8) and u.path not in ('/', '/api/days', '/api/people', '/api/ranking'):
            return self.send(400, {'error': '날짜는 YYYYMMDD'})
        try:
            if u.path == '/':
                return self.send(200, PAGE.read_bytes(), 'text/html; charset=utf-8')
            if u.path == '/api/people':
                return self.send(200, {'me': ME, 'others': [p for p in people() if p != ME]})
            if u.path == '/api/ranking':
                return self.send(200, ranking(q.get('w')))
            if u.path == '/api/days':
                return self.send(200, days_of(person))
            if u.path == '/api/day':
                return self.send(200, day_data(day, person))
            if u.path == '/api/bars' and code.isdigit():
                b = bars(day, code, source(person)[0])
                return self.send(200, [] if b is None else b[['hhmm', 'open', 'high', 'low', 'close']].values.tolist())
            if u.path == '/api/lines':
                return self.send(200, lines(day, [c for c in q.get('codes', '').split(',') if c.isdigit()]))
            self.send(404, {'error': '없는 주소'})
        except Exception as ex:
            self.send(500, {'error': str(ex)})

    def send(self, status, body, kind='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, default=float).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):                    # 요청마다 화면에 찍지 않는다
        pass


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.getenv('DASHBOARD_PORT') or 8642)   # 8000은 다른 개발 서버와 겹쳐서
    print(f'http://localhost:{port} (끝내려면 Ctrl+C)')
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
