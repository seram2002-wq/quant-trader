"""장 마감 반전 v3 사후 분석: 필터가 피한 손실·놓친 수익, 필터를 끈 경우, v1 그림자와 비교

    python tools/v3_report.py             오늘
    python tools/v3_report.py 20261125    그날

run.py가 장 마감 뒤 분봉을 저장한 다음 자동으로 부른다. 판단 기록(data/paper_close_reversal_v3/decisions/)과
분봉(data/minute/)을 읽는다. 매매에는 쓰지 않는다.

가상 매매: 판단 기록의 가격에 사서 15:15 직전 분봉 종가에 판 것으로 계산 (가상 장부와 같은 슬리피지·수수료·세금, 240만 원)
    제외 종목    : 처음 제외한 시각의 가격으로. 마이너스면 피한 손실, 플러스면 놓친 수익
    필터 끈 v3   : 판단 시각 순서대로, 하락 조건 후보를 많이 떨어진 순으로 4종목까지 (같은 종목은 한 번)
    필터 효과    = v3 실제 손익 - 필터 끈 v3     (거른 종목 대신 산 종목까지 반영한 필터의 실제 가치)
    종목 범위 효과 = 필터 끈 v3 - v1 그림자 실제 손익 (판단 시각 차이도 섞여 있음)
    ⑥ 직전 60분 거래량 비율 = (t-60분 ~ t) 분당 거래량 / (09:30 ~ t-60분) 분당 평균 (판단 시각 t까지의 자료만)
    마감 거래량 비율 = (14:30 ~ 15:30) / (09:30 ~ 14:30). 매수 뒤의 자료라 분석용으로만
shortcut: 필터 끈 v3는 판단 기록이 있는 시각만 다시 돌린다. 실제 v3 자리가 다 차서 기록이 멈춘 뒤는 모르지만,
          후보가 더 많은 필터 끈 쪽이 항상 먼저 자리가 차므로 결과는 같다
결과: data/paper_close_reversal_v3/report.csv (하루 한 줄, 다시 돌리면 그날 줄을 바꿈)
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config                                        # noqa: E402

BOOK, SHADOW = 'paper_close_reversal_v3', 'paper_close_reversal'
BUDGET, SLOTS, EXIT = 2_400_000, 4, '151500'
NAN = float('nan')


def bars(day, code):
    path = ROOT / 'data' / 'minute' / day / f'{code}.csv'
    if not path.exists():
        return None
    b = pd.read_csv(path, dtype={'time': str})
    return b.assign(time=b['time'].str.zfill(6)).set_index('time')


def price_before(b, t):
    x = b[b.index < t]
    return float(x['close'].iloc[-1]) if len(x) else NAN


def trade(entry, exit_):
    """가상 장부(PaperBroker)와 같은 계산의 손익 (원)"""
    fill = entry * (1 + config.SLIPPAGE)
    qty = int(BUDGET // (fill * (1 + config.FEE_RATE)))
    if qty <= 0 or exit_ != exit_:
        return NAN
    cost = round(fill * qty)
    cost += round(cost * config.FEE_RATE)
    amount = round(exit_ * (1 - config.SLIPPAGE) * qty)
    return amount - round(amount * config.FEE_RATE) - round(amount * config.STOCK_SELL_TAX) - cost


def vol_ratio(b, start, end, base_end):
    recent = b[(b.index >= start) & (b.index < end)]['volume'].mean()
    base = b[(b.index >= '093000') & (b.index < base_end)]['volume'].mean()
    return recent / base if base else NAN


def realized(book, day):
    path = ROOT / 'data' / book / 'trades.csv'
    if not path.exists():
        return NAN
    t = pd.read_csv(path, dtype={'code': str})
    sells = t[(t['side'] == 'SELL') & t['time'].str.startswith(f'{day[:4]}-{day[4:6]}-{day[6:]}')]
    return float(pd.to_numeric(sells['profit']).sum())


def unfiltered_picks(d):
    """필터를 끈 v3가 샀을 종목 [(code, 가격)]"""
    picks = {}
    for _, g in d.groupby('time', sort=True):
        for code, price in g.sort_values('r_open')[['code', 'price']].itertuples(index=False):
            if len(picks) < SLOTS and code not in picks:
                picks[code] = price
    return list(picks.items())


def analyze(day):
    """(종목별 표, 하루 요약) 또는 판단 기록이 없으면 None"""
    path = ROOT / 'data' / BOOK / 'decisions' / f'{day}.csv'
    if not path.exists():
        return None
    d = pd.read_csv(path, dtype={'code': str, 'time': str})
    first = d.groupby('code').first()
    excluded = d[d['passed'] == 0].groupby('code').first()
    rows = []
    for code, f in first.iterrows():
        b = bars(day, code)
        exit_ = price_before(b, EXIT) if b is not None else NAN
        t = f['time'].replace(':', '')
        t60 = (datetime.strptime(t, '%H%M%S') - timedelta(minutes=60)).strftime('%H%M%S')
        ex = excluded.loc[code] if code in excluded.index else None
        rows.append({'code': code, 'name': f['name'], 'sector': f['sector'], 'first': f['time'],
                     'excluded': int(ex is not None), 'spread': (ex if ex is not None else f)['spread'],
                     'near_low': f['near_low'], 'us_rescue': int(d.loc[d['code'] == code, 'us_rescue'].max()),
                     'vol_1h': vol_ratio(b, t60, t, t60) if b is not None else NAN,
                     'vol_close': vol_ratio(b, '143000', '153000', '143000') if b is not None else NAN,
                     'exit': exit_, 'pnl': trade((ex if ex is not None else f)['price'], exit_)})
    table = pd.DataFrame(rows)
    ex = table[table['excluded'] == 1]['pnl']
    picks = unfiltered_picks(d)
    exit_of = dict(zip(table['code'], table['exit']))
    unfiltered = sum(trade(p, exit_of.get(c, NAN)) for c, p in picks)
    v3, v1 = realized(BOOK, day), realized(SHADOW, day)
    summary = {'day': day, 'candidates': len(table), 'excluded': len(ex), 'no_peer': int(d.loc[d['peers'].isna(), 'code'].nunique()),
               'us_rescue': int(table['us_rescue'].sum()),
               'avoided_loss': -ex[ex < 0].sum(), 'missed_gain': ex[ex > 0].sum(),
               'v3': v3, 'unfiltered': unfiltered, 'filter_effect': v3 - unfiltered,
               'v1_shadow': v1, 'range_effect': unfiltered - v1,
               'unfiltered_picks': ' '.join(c for c, _ in picks)}
    return table, summary


def run(day=None, log=print):
    day = day or datetime.now().strftime('%Y%m%d')
    out = analyze(day)
    if out is None:
        log(f'v3 판단 기록 없음 ({day})')
        return None
    table, s = out
    path = ROOT / 'data' / BOOK / 'report.csv'
    old = pd.read_csv(path, dtype={'day': str}) if path.exists() else pd.DataFrame()
    new = pd.concat([old[old['day'] != day] if len(old) else old, pd.DataFrame([s])], ignore_index=True)
    new.sort_values('day').to_csv(path, index=False, encoding='utf-8')
    log(f'v3 사후 분석 {day}: 후보 {s["candidates"]}, 제외 {s["excluded"]} '
        f'(피한 손실 {s["avoided_loss"]:,.0f}원, 놓친 수익 {s["missed_gain"]:,.0f}원) | '
        f'v3 {s["v3"]:+,.0f} / 필터 끈 v3 {s["unfiltered"]:+,.0f} / v1 그림자 {s["v1_shadow"]:+,.0f} → '
        f'필터 효과 {s["filter_effect"]:+,.0f}, 종목 범위 효과 {s["range_effect"]:+,.0f}')
    return table, s


if __name__ == '__main__':
    res = run(sys.argv[1] if len(sys.argv) > 1 else None)
    if res:
        pd.set_option('display.width', 200)
        print(res[0].round(4).to_string(index=False))
