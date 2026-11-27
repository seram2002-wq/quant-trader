"""팀 전광판(claude.ai 아티팩트)에 올릴 자료 파일을 만든다 — 웹 전광판(tools/dashboard.py)과 같은 계산

    python -m tools.artifact_export            data/artifact/*.csv

사람: 나(.env TEAM_NAME, 이 PC의 data/)와 공유 폴더(TEAM_DIR)의 팀원들
    daily.csv     사람·날짜·장부별 하루 손익
    pnl.csv       장부별 하루 손익 곡선 (자금 대비 %, 1분 단위)
    index.csv     KODEX 200 시가 대비 % (1분 단위)
    trades.csv    매매
    bars.csv      그날 매매한 종목과 v3 후보·업종 동료의 1분봉
    held.csv      그날 시작할 때 들고 있던 종목 (매매 없는 날도 차트를 보게)
    v3.csv        v3 판단 (v3를 돌리는 사람만), v3_effect.csv 사람·날짜별 필터·종목 범위 효과
    ranking.csv   주간 랭킹 (모의 장부만), ranking_curve.csv 그 주 누적 수익률
아티팩트에 올리는 일은 Claude가 한다 (이 스크립트는 파일만 만든다).
"""
import csv
import sys

from tools import dashboard as d

OUT = d.DATA / 'artifact'


def write(name, fields, rows):
    with open(OUT / name, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def run(log=print):
    OUT.mkdir(parents=True, exist_ok=True)
    daily, pnl, index, trades, bars, v3, effect, held = [], [], [], [], [], [], [], []
    persons = [d.ME] + [p for p in d.people() if p != d.ME]
    index_days, bar_keys = set(), set()
    for person in persons:
        root = d.source(person)[0]
        for day in d.days_of(person):
            x = d.day_data(day, person)
            if not x['books']:                       # 매매 없는 날도 장 마감 총자산이 있으면 넣는다 (days_of가 고른 날)
                continue
            for b in x['books']:
                daily.append({'person': person, 'day': day, 'book': b['label'], 'pnl': b['pnl']})
                pnl += [{'person': person, 'day': day, 'book': b['label'], 'hhmm': m, 'pct': round(v, 4)}
                        for m, v in b['curve']]
            if day not in index_days and x.get('index'):
                index_days.add(day)
                index += [{'day': day, 'hhmm': m, 'pct': round(v, 4)} for m, v in x['index']]
            for t in x['trades']:
                trades.append({'person': person, 'day': day, **{k: t[k] for k in
                               ('book', 'side', 'code', 'name', 'hhmm', 'qty', 'price', 'profit')}})
            names = dict(x['stocks'], **x.get('names', {}))
            codes = {t['code'] for t in x['trades']} | set(x['held'])
            held += [{'person': person, 'day': day, 'code': c, 'name': n} for c, n in x['held'].items()]
            for r in x['v3']:
                codes |= {r['code'], *str(r.get('peers') or '').split()}
                v3.append({'person': person, 'day': day, 'code': r['code'], 'name': r['name'], 'sector': r['sector'],
                           'first': r['first'], 'verdict': '제외' if r['excluded'] else '통과',
                           'spread': r['spread'], 'near_low': r['near_low'], 'exit': r['exit'], 'pnl': r['pnl'],
                           'peers': r.get('peers') or ''})
            for code in sorted(codes - {''}):           # 순서를 고정해야 내용이 같으면 파일도 같음
                if (day, code) in bar_keys:
                    continue
                b = d.bars(day, code, root)
                if b is None:
                    continue
                bar_keys.add((day, code))
                bars += [{'day': day, 'code': code, 'name': names.get(code, code), 'hhmm': m,
                          'open': o, 'high': h, 'low': lo, 'close': c}
                         for m, o, h, lo, c in b[['hhmm', 'open', 'high', 'low', 'close']].values.tolist()]
            if x['report'] and person not in {e['person'] for e in effect}:
                effect += [{'person': person, 'day': r['day'], 'filter_effect': r['filter_effect'], 'range_effect': r['range_effect']}
                          for r in x['report']]
    rank, curve = [], []
    weeks = d.ranking()['weeks']
    for w in weeks:
        r = d.ranking(w)
        for i, x in enumerate(r['rows'], 1):
            rank.append({'week': w, 'rank': i, 'person': x['person'], 'book': x['label'], 'ret': round(x['ret'], 4),
                         'pnl': round(x['pnl']), 'sells': x['sells'], 'win': x['win'], 'worst': x['worst']})
            curve += [{'week': w, 'person': x['person'], 'book': x['label'], 'day': day, 'pct': round(v, 4)}
                      for day, v in x['curve']]
    n = {
        'daily.csv': write('daily.csv', ['person', 'day', 'book', 'pnl'], daily),
        'pnl.csv': write('pnl.csv', ['person', 'day', 'book', 'hhmm', 'pct'], pnl),
        'index.csv': write('index.csv', ['day', 'hhmm', 'pct'], index),
        'trades.csv': write('trades.csv', ['person', 'day', 'book', 'side', 'code', 'name', 'hhmm', 'qty', 'price',
                                           'profit'], trades),
        'bars.csv': write('bars.csv', ['day', 'code', 'name', 'hhmm', 'open', 'high', 'low', 'close'], bars),
        'v3.csv': write('v3.csv', ['person', 'day', 'code', 'name', 'sector', 'first', 'verdict', 'spread', 'near_low', 'exit',
                                   'pnl', 'peers'], v3),
        'v3_effect.csv': write('v3_effect.csv', ['person', 'day', 'filter_effect', 'range_effect'], effect),
        'held.csv': write('held.csv', ['person', 'day', 'code', 'name'], held),
        'ranking.csv': write('ranking.csv', ['week', 'rank', 'person', 'book', 'ret', 'pnl', 'sells', 'win', 'worst'],
                             rank),
        'ranking_curve.csv': write('ranking_curve.csv', ['week', 'person', 'book', 'day', 'pct'], curve),
    }
    log('아티팩트 자료 : ' + ', '.join(f'{k} {v}줄' for k, v in n.items()) + f' → {OUT}')
    return n


if __name__ == '__main__':
    run()
    sys.exit(0)
