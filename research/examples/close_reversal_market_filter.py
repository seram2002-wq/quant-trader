"""장 마감 반전 v1에 '시장이 시가 대비 빠진 날만' 조건을 붙이면 나아지는지 — 2026-11-26

    python -m research.examples.close_reversal_market_filter          (장 마감 뒤에. 한국투자 API를 부름)

봉인 해제: 한국투자 API의 지난 1분봉은 약 1년 전(2025-12)까지만 있어, 2025년 이후 봉인 구간을 쓴다 (사용자 승인 11-26).
    그래서 결과가 좋아도 앞으로 몇 달의 실전 기록으로 다시 확인해야 한다 (손대지 않은 검증 구간이 없음).

재현하는 v1 (매일, 2025-12-01 ~ marcap 마지막 날)
    종목   : 그날 거래대금(marcap Amount) 상위 보통주 11개 (실전은 14:30 실시간 거래대금 상위 30에서 ETF를 뺀 약 11개)
    매수   : 14:29 1분봉 종가가 그날 시가 대비 -15% 초과 ~ -2% 이하. 가장 많이 빠진 순으로 4종목, 종목당 240만 원
    매도   : 15:14 1분봉 종가 (15:15 일괄 매도 직전). 비용은 가상 장부와 같게 (tools/v3_report.trade)
    shortcut: 판단은 14:30 한 번만 (실전은 15:00까지 빈 자리를 다시 봄), 그날 거래대금은 장 끝까지라 조금 미리 아는 셈
조건 (실행 전 확정)
    시장   = KODEX 200(069500)의 14:29 종가 ÷ 그날 첫 거래 봉 시가 - 1
    주 조건: 시장 < 0 인 날만 산다.   참고만: 시장 ≤ -0.5%, ≤ -1%
판정 (실행 전 확정): 주 조건이 아래를 모두 만족하면 '근거 있음', 아니면 '근거 없음'
    ① 조건 붙인 쪽의 거래당 평균 손익 > 0   ② 조건 붙인 쪽 - 조건 없는 쪽(거래당 평균) > 0 이 앞·뒤 반기 모두
    ③ 조건 붙인 쪽 거래 100건 이상
받은 분봉: data/minute_hist/YYYYMMDD/<종목>_<마지막 시각>.csv (다시 돌리면 받은 것은 건너뜀)
결과: data/research/close_reversal_market_filter.csv (거래별)
"""
import csv
import re
import sys
import time

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from research.data import RESEARCH
from tools.v3_report import trade
from trader import marcap
from trader.kis_client import KISClient, KISError

ROOT = RESEARCH.parent.parent
load_dotenv(ROOT / '.env', override=True)
HIST = ROOT / 'data' / 'minute_hist'
START, TOP, SLOTS, DROP, MAX_DROP, INDEX = '2025-12-01', 11, 4, 0.02, 0.15, '069500'
NAME_EXCLUDE = re.compile(r'스팩|리츠|ETF|ETN|\d우[A-Z]?$|우B$|우\(전환\)$')
FIELDS = ['time', 'open', 'high', 'low', 'close', 'volume']


def minute(client, code, day, until):
    """그날 until까지 120개 1분봉 (캐시). [] 이면 자료 없음"""
    path = HIST / day / f'{code}_{until}.csv'
    if path.exists():
        return pd.read_csv(path, dtype={'time': str})
    rows = []
    for attempt in range(3):
        try:
            d = client._get('/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice', 'FHKST03010230',
                            {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': code, 'FID_INPUT_HOUR_1': until,
                             'FID_INPUT_DATE_1': day, 'FID_PW_DATA_INCU_YN': 'Y', 'FID_FAKE_TICK_INCU_YN': ''})
            rows = [{'time': r['stck_cntg_hour'], 'open': float(r['stck_oprc']), 'high': float(r['stck_hgpr']),
                     'low': float(r['stck_lwpr']), 'close': float(r['stck_prpr']), 'volume': float(r['cntg_vol'])}
                    for r in d.get('output2', []) or [] if r.get('stck_bsop_date') == day and r.get('stck_cntg_hour')]
            break
        except (KISError, OSError) as ex:
            print(f'다시 시도 {day} {code} {until}: {ex}', flush=True)
            time.sleep(2)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r['time']))
    return pd.read_csv(path, dtype={'time': str})


def close_before(b, t):
    x = b[(b['time'] < t) & (b['volume'] > 0)]
    return float(x['close'].iloc[-1]) if len(x) else np.nan


def market(client, day):
    """KODEX 200 (14:29 종가 ÷ 첫 거래 봉 시가 - 1, 매수 뒤 15:14까지 등락)"""
    early, late = minute(client, INDEX, day, '105900'), minute(client, INDEX, day, '151500')
    traded = early[early['volume'] > 0]
    if traded.empty or late.empty:
        return np.nan, np.nan
    o, p, e = traded['open'].iloc[0], close_before(late, '143000'), close_before(late, '151500')
    return p / o - 1, e / p - 1


def main():
    df = pd.read_parquet(marcap.path_of(2025), columns=['Date', 'Code', 'Name', 'Dept', 'Market', 'Open', 'Low', 'Amount'])
    df = pd.concat([df, pd.read_parquet(marcap.path_of(2026), columns=list(df.columns))])
    df = df[(df['Date'] >= START) & df['Market'].isin(marcap.MARKETS) & df['Code'].str.endswith('0')]
    df = df[~df['Name'].fillna('').str.contains(NAME_EXCLUDE) & ~df['Dept'].fillna('').str.contains('관리|SPAC|환기')]
    client = KISClient()
    rows = []
    days = sorted(df['Date'].unique())
    for i, date in enumerate(days):
        day = pd.Timestamp(date).strftime('%Y%m%d')
        top = df[df['Date'] == date].nlargest(TOP, 'Amount')
        mkt, mkt_after = market(client, day)
        cands = []
        for r in top[top['Low'] <= top['Open'] * (1 - DROP)].itertuples():       # 하루 중 -2%까지 안 빠졌으면 후보 아님
            b = minute(client, r.Code, day, '151500')
            entry, exit_ = close_before(b, '143000'), close_before(b, '151500')
            drop = entry / r.Open - 1
            if -MAX_DROP < drop <= -DROP:
                cands.append((drop, r.Code, r.Name, entry, exit_))
        for drop, code, name, entry, exit_ in sorted(cands)[:SLOTS]:
            rows.append({'day': day, 'code': code, 'name': name, 'drop': drop, 'entry': entry, 'exit': exit_,
                         'pnl': trade(entry, exit_), 'ret': exit_ / entry - 1, 'mkt': mkt, 'mkt_after': mkt_after})
        if i % 20 == 0:
            print(f'{day} 까지 {i + 1}/{len(days)}일, 거래 {len(rows)}건', flush=True)
    t = pd.DataFrame(rows).dropna(subset=['pnl'])
    t.to_csv(RESEARCH / 'close_reversal_market_filter.csv', index=False, encoding='utf-8')
    judge(t)


def judge(t):
    mid = sorted(t['day'].unique())[len(t['day'].unique()) // 2]
    print(f'\n거래 {len(t)}건, {t["day"].nunique()}일 ({t["day"].min()} ~ {t["day"].max()}), 반기 경계 {mid}')
    print('조건       거래  거래당 평균(원)  승률   하루 평균(원)   앞 반기 차이   뒤 반기 차이')
    base = t['pnl'].mean()
    halves = [t[t['day'] < mid], t[t['day'] >= mid]]
    out = {}
    for label, f in [('없음', lambda x: x['mkt'] == x['mkt']), ('시장 < 0', lambda x: x['mkt'] < 0),
                     ('시장 ≤ -0.5%', lambda x: x['mkt'] <= -0.005), ('시장 ≤ -1%', lambda x: x['mkt'] <= -0.01),
                     ('시장 ≥ 0 (반대)', lambda x: x['mkt'] >= 0)]:
        s = t[f(t)]
        diffs = [h[f(h)]['pnl'].mean() - h['pnl'].mean() for h in halves]
        out[label] = (s, diffs)
        print(f'{label:<12}{len(s):>5}{s["pnl"].mean():>14,.0f}{(s["pnl"] > 0).mean():>8.0%}'
              f'{s.groupby("day")["pnl"].sum().mean():>14,.0f}{diffs[0]:>14,.0f}{diffs[1]:>14,.0f}')
    s, diffs = out['시장 < 0']
    ok = s['pnl'].mean() > 0 and all(d > 0 for d in diffs) and len(s) >= 100
    print(f'\n판정 (시장 < 0): {"근거 있음" if ok else "근거 없음"} '
          f'(거래당 {s["pnl"].mean():+,.0f}원, 반기 차이 {diffs[0]:+,.0f} / {diffs[1]:+,.0f}, {len(s)}건, 조건 없는 쪽 {base:+,.0f}원)')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--judge':          # 받은 결과로 표만 다시
        judge(pd.read_csv(RESEARCH / 'close_reversal_market_filter.csv', dtype={'day': str}))
    else:
        main()
