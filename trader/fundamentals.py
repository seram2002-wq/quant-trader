"""DART 재무제표(tools/fetch_dart.py가 받은 accounts.csv)를 날짜별로 쓸 수 있는 값으로 정리

공시한 날(rcept_no 앞 8자리) 다음 거래일부터만 그 보고서 값을 쓴다 (미래 정보 사용 방지).
    재무상태 (자산, 부채, 자본)     : 가장 최근에 공시된 보고서의 값
    손익 (매출, 영업이익, 순이익)   : 최근 4개 분기 합 (TTM)
                                      4분기 = 사업보고서 1년치 - (1·2·3분기)
연결재무제표가 있으면 연결, 없으면 개별 재무제표를 쓴다.
"""
from pathlib import Path

import numpy as np
import pandas as pd

ACCOUNTS_FILE = Path(__file__).resolve().parent.parent / 'data' / 'research' / 'dart' / 'accounts.csv'
QUARTER = {'11013': 1, '11012': 2, '11014': 3, '11011': 4}
BALANCE = {'자산총계': 'assets', '부채총계': 'liabilities', '자본총계': 'equity'}
FLOW = {'매출액': 'sales', '영업이익': 'op', '당기순이익': 'ni'}


def load_events(path=ACCOUNTS_FILE):
    """종목별·분기별 값과 공시일. 돌려주는 표의 열:
    code, year, q, filed(공시일), assets, liabilities, equity, sales_ttm, op_ttm, ni_ttm
    """
    d = pd.read_csv(path, dtype=str)
    d = d[d['account_nm'].isin(list(BALANCE) + list(FLOW))].copy()
    d['value'] = pd.to_numeric(d['thstrm_amount'].str.replace(',', ''), errors='coerce')
    d['q'] = d['reprt_code'].map(QUARTER)
    d['year'] = d['bsns_year'].astype(int)
    d['filed'] = pd.to_datetime(d['rcept_no'].str[:8], format='%Y%m%d', errors='coerce')
    # 연결 우선: 같은 회사·보고서에 연결(CFS)이 있으면 개별(OFS)은 버린다
    has_cfs = d[d['fs_div'] == 'CFS'].groupby(['stock_code', 'year', 'q']).size().rename('cfs')
    d = d.join(has_cfs, on=['stock_code', 'year', 'q'])
    d = d[(d['fs_div'] == 'CFS') | d['cfs'].isna()]
    d = d.drop_duplicates(['stock_code', 'year', 'q', 'account_nm'], keep='first')
    wide = d.pivot_table(index=['stock_code', 'year', 'q'], columns='account_nm',
                         values='value', aggfunc='first')
    filed = d.groupby(['stock_code', 'year', 'q'])['filed'].min()
    wide = wide.rename(columns={**BALANCE, **FLOW}).join(filed).reset_index()
    wide = wide.rename(columns={'stock_code': 'code'})
    for c in list(BALANCE.values()) + list(FLOW.values()):
        if c not in wide:
            wide[c] = np.nan

    # 분기 손익: 1~3분기는 그대로, 4분기는 1년치에서 1~3분기를 뺀다
    out = []
    for code, g in wide.groupby('code'):
        g = g.set_index(['year', 'q']).sort_index()
        qv = {}
        for (y, q), row in g.iterrows():
            if q < 4:
                qv[(y, q)] = row[list(FLOW.values())]
            else:
                parts = [qv.get((y, k)) for k in (1, 2, 3)]
                if all(p is not None for p in parts):
                    qv[(y, 4)] = row[list(FLOW.values())] - sum(parts)
        for (y, q), row in g.iterrows():
            last4 = [(y, q)]
            yy, qq = y, q
            for _ in range(3):
                yy, qq = (yy, qq - 1) if qq > 1 else (yy - 1, 4)
                last4.append((yy, qq))
            if all(k in qv for k in last4):
                ttm = sum(qv[k] for k in last4)
            elif q == 4:
                ttm = row[list(FLOW.values())]            # 분기 자료가 모자라면 사업보고서 1년치
            else:
                ttm = pd.Series(np.nan, index=list(FLOW.values()))
            out.append({'code': code, 'year': y, 'q': q, 'filed': row['filed'],
                        'assets': row['assets'], 'liabilities': row['liabilities'],
                        'equity': row['equity'],
                        **{f'{k}_ttm': ttm[k] for k in FLOW.values()}})
    ev = pd.DataFrame(out).dropna(subset=['filed'])
    return ev.sort_values(['code', 'filed', 'year', 'q'])


def daily(ev, column, dates, codes, max_age=400):
    """날짜 × 종목 표: 각 날짜에 쓸 수 있던 가장 최근 값 (공시 다음 거래일부터)"""
    dates = pd.DatetimeIndex(dates)
    pos = dates.searchsorted(ev['filed'].values, side='right')
    e = ev.assign(avail=[dates[p] if p < len(dates) else pd.NaT for p in pos]).dropna(subset=['avail'])
    e = e.sort_values(['avail', 'year', 'q'])
    period = e['year'] * 10 + e['q']
    e = e[period >= period.groupby(e['code']).cummax()]      # 늦게 낸 옛 보고서(정정 등)로 되돌아가지 않게
    e = e.drop_duplicates(['code', 'avail'], keep='last')
    m = e.pivot(index='avail', columns='code', values=column)
    m = m.reindex(index=dates, columns=codes)
    return m.ffill(limit=max_age)


def latest(ev, asof):
    """asof 날짜까지 공시된 종목별 최신 값 (실시간 전략용). asof 당일 공시는 제외"""
    e = ev[ev['filed'] < pd.Timestamp(asof)]
    return e.sort_values(['year', 'q', 'filed']).groupby('code').last()
