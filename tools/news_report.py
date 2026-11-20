"""뉴스 판정 사후 분석: 판정별로 포착 뒤 주가가 어떻게 움직였나

    python tools/news_report.py        → results/news_report.md (그리고 화면 출력)

data/news/YYYYMMDD.csv(run.py NewsCheck)를 같은 날 data/minute/YYYYMMDD/<종목코드>.csv와 맞춘다.
포착 시각 = 뉴스 파일의 time 열 (NewsCheck가 그 기사를 처음 본 시각).

미래 정보 없이 맞추는 규칙
    분봉 HHMM00은 그 1분 동안의 봉이라 끝나야 종가를 안다
    포착 가격 = 포착한 분 직전에 끝난 봉의 종가. 장 시작 전 포착이면 첫 봉 시가, 그때부터 시간을 센다
    N분 뒤 가격 = (기준 시각 + N분) 직전에 끝난 봉의 종가. 장 마감을 넘으면 빈칸 (장마감 값과 섞지 않음)
    장마감 = 그날 마지막 봉 종가. 장 마감 뒤 포착은 따로 세고 뺀다
    초과 = 같은 구간 KODEX 200(069500) 수익률을 뺀 값 (시장 전체 움직임 제외)

집계
    같은 날 같은 종목에 같은 판정 기사가 여러 건이면 처음 포착한 것 하나만 센다 (같은 주가 움직임을 여러 번 세지 않게)
    오탐 = 악재인데 장마감 초과 수익률 > 0, 호재인데 < 0 (KODEX 200 분봉이 없으면 그냥 수익률로)
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
NEWS_DIR = ROOT / 'data' / 'news'
MINUTE_DIR = ROOT / 'data' / 'minute'
OUT = ROOT / 'results' / 'news_report.md'
BENCH = '069500'
HORIZONS = {'5분': 5, '15분': 15, '30분': 30}
COLS = list(HORIZONS) + ['장마감']
ORDER = ['악재', '예외', '혼재', '호재', '중립']


def load_bars(day, code):
    p = MINUTE_DIR / day / f'{code}.csv'
    if not p.exists():
        return None
    b = pd.read_csv(p, dtype={'date': str, 'time': str})
    b['ts'] = pd.to_datetime(b['date'] + b['time'].str.zfill(6), format='%Y%m%d%H%M%S')
    return b.sort_values('ts').reset_index(drop=True) if len(b) else None


def returns(bars, checked):
    """{'5분', '15분', '30분', '장마감': 수익률}. 장 마감 뒤 포착이면 None"""
    minute = checked.floor('min')
    first, last = bars['ts'].iloc[0], bars['ts'].iloc[-1]
    if minute > last:
        return None
    if minute <= first:
        start, entry = first, bars['open'].iloc[0]
    else:
        start, entry = minute, bars.loc[bars['ts'] < minute, 'close'].iloc[-1]
    out = {}
    for k, m in HORIZONS.items():
        end = start + pd.Timedelta(minutes=m)
        out[k] = (bars.loc[bars['ts'] < end, 'close'].iloc[-1] / entry - 1
                  if end <= last + pd.Timedelta(minutes=1) else float('nan'))
    out['장마감'] = bars['close'].iloc[-1] / entry - 1
    return out


def read_news():
    files = sorted(NEWS_DIR.glob('*.csv')) if NEWS_DIR.exists() else []
    if not files:
        return pd.DataFrame()
    df = pd.concat([pd.read_csv(f, dtype=str, keep_default_na=False, encoding='utf-8-sig') for f in files],
                   ignore_index=True)
    df['checked'] = pd.to_datetime(df['time'])
    return df


def match(news):
    """뉴스 한 줄마다 수익률·초과 수익률을 붙인다. (맞춘 표, 장 마감 뒤 포착 수, 분봉 없는 수)"""
    rows, after, missing, cache = [], 0, 0, {}

    def bars_of(day, code):
        if (day, code) not in cache:
            cache[day, code] = load_bars(day, code)
        return cache[day, code]

    for r in news.itertuples(index=False):
        day = r.checked.strftime('%Y%m%d')
        bars = bars_of(day, r.code)
        if bars is None:
            missing += 1
            continue
        ret = returns(bars, r.checked)
        if ret is None:
            after += 1
            continue
        bench = bars_of(day, BENCH)
        bret = returns(bench, r.checked) if bench is not None else None
        row = r._asdict()
        for k in COLS:
            row[k] = ret[k]
            row['초과 ' + k] = ret[k] - bret[k] if bret else float('nan')
        rows.append(row)
    return pd.DataFrame(rows), after, missing


def pct(x):
    return '' if pd.isna(x) else f'{x:+.2%}'


def build(news):
    if news.empty:
        return '# 뉴스 판정 사후 분석\n\n아직 data/news/에 기록이 없습니다.\n'
    m, after, missing = match(news)
    lines = ['# 뉴스 판정 사후 분석\n',
             f'뉴스 {len(news)}건 ({news["checked"].dt.date.min()} ~ {news["checked"].dt.date.max()}), '
             f'분봉과 맞춘 것 {len(m)}건, 장 마감 뒤 포착 {after}건, 그날 분봉 없음 {missing}건.',
             '같은 날·같은 종목·같은 판정은 처음 포착한 것 하나만 셉니다. 초과 = KODEX 200 대비.\n']
    if m.empty:
        return '\n'.join(lines) + '\n맞출 수 있는 기사가 없습니다 (분봉은 run.py가 장 마감 뒤에 저장).\n'
    m['day'] = m['checked'].dt.date
    first = m.sort_values('checked').drop_duplicates(['day', 'code', 'verdict'])

    lines += ['## 판정별 평균 수익률 (괄호는 오른 비율)\n',
              '| 판정 | 기사 | 종목·일 | ' + ' | '.join(COLS) + ' | 초과 장마감 |',
              '|---|---|---|' + '---|' * (len(COLS) + 1)]
    for v in [v for v in ORDER if v in set(first['verdict'])]:
        g = first[first['verdict'] == v]
        cells = [f'{pct(g[k].mean())} ({(g[k].dropna() > 0).mean():.0%})' if g[k].notna().any() else ''
                 for k in COLS]
        lines.append(f'| {v} | {(m["verdict"] == v).sum()} | {len(g)} | ' + ' | '.join(cells)
                     + f' | {pct(g["초과 장마감"].mean())} |')

    first = first.assign(k=first['초과 장마감'].fillna(first['장마감']))   # 걸러 내기 전에 붙인다 (빈 표에 붙이면 행이 생김)
    for v, wrong, label in (('악재', first['k'] > 0, '악재인데 오른 종목'), ('호재', first['k'] < 0, '호재인데 내린 종목')):
        fp = first[(first['verdict'] == v) & wrong].sort_values('k', ascending=(v == '호재'))
        total = (first['verdict'] == v).sum()
        lines += [f'\n## 오탐: {label} ({len(fp)} / {total})\n']
        if fp.empty:
            lines.append('없음')
            continue
        lines += ['| 포착 | 종목 | 장마감 | 초과 | 키워드 | 제목 |', '|---|---|---|---|---|---|']
        for _, r in fp.head(20).iterrows():
            lines.append(f'| {r["checked"]:%m-%d %H:%M} | {r["name"]}({r["code"]}) | {pct(r["장마감"])} | '
                         f'{pct(r["초과 장마감"])} | {r["keywords"]} | [{r["title"]}]({r["link"]}) |')
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    text = build(read_news())
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(text, encoding='utf-8')
    print(text)
    print(f'→ {OUT.relative_to(ROOT)}')
