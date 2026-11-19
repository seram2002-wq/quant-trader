"""가상 매매 결과 보고서 만들기

    python report.py

data/<장부>/trades.csv를 읽어서 results/<장부>.md를 새로 만든다.
quantstats가 설치되어 있으면 장부마다 성과 분석 보고서(results/<장부>_tearsheet.html, 샤프·소르티노·
최대 낙폭·월별 수익 등, KODEX 200과 비교)와 장부끼리 비교표(results/comparison.md)도 만든다.
(data와 results 폴더는 모두 git에 올리지 않고 각자 컴퓨터에만 둔다)
보고서는 매번 data에서 다시 만드므로 직접 고치지 않는다.
관찰한 내용이나 메모는 results/journal.md에 따로 적는다.
"""
import csv
import json
import re
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

import config

ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / 'data'
RESULTS_DIR = ROOT / 'results'


def won(x):
    return f'{x:+,.0f}'


def read_trades(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def pair_trades(rows):
    """매수와 매도를 종목별로 짝지어 한 건의 거래로 만든다."""
    open_buys, trades = {}, []
    for r in rows:
        if r['side'] == 'BUY':
            open_buys[r['code']] = r
        elif r['side'] == 'SELL':
            b = open_buys.pop(r['code'], None)
            cost = float(b['amount']) + float(b['fee']) if b else 0
            profit = float(r['profit'] or 0)
            drop = re.search(r'대비 ([+-][\d.]+%)', b['reason']) if b else None
            hold = ''
            if b:
                t0 = datetime.strptime(b['time'], '%Y-%m-%d %H:%M:%S')
                t1 = datetime.strptime(r['time'], '%Y-%m-%d %H:%M:%S')
                minutes = int((t1 - t0).total_seconds() // 60)
                days = (t1.date() - t0.date()).days
                hold = f'{days}일' if days else f'{minutes}분'
            trades.append({
                'date': r['time'][:10], 'name': r['name'], 'code': r['code'],
                'buy_time': b['time'][11:16] if b else '', 'sell_time': r['time'][11:16],
                'buy_price': float(b['price']) if b else 0, 'sell_price': float(r['price']),
                'qty': int(r['qty']), 'signal': drop.group(1) if drop else (b['reason'] if b else ''),
                'sell_reason': r['reason'], 'hold': hold,
                'version': r.get('version') or (b.get('version') if b else '') or '',
                'profit': profit, 'rate': profit / cost * 100 if cost else 0,
                'cost': float(r['fee']) + float(r['tax']) + (float(b['fee']) if b else 0),
            })
    return trades, open_buys


def capital_of(book):
    """장부의 시작 자금: config.STRATEGIES에서 찾고, 없으면 1,000만 원"""
    for spec in getattr(config, 'STRATEGIES', []):
        module = spec['strategy'].split('.')[0]
        if book == f"{spec['account']}_{module}":
            return spec['capital']
    return 10_000_000


def build(book):
    rows = read_trades(DATA_ROOT / book / 'trades.csv')
    trades, still_open = pair_trades(rows)
    state = json.loads((DATA_ROOT / book / 'state.json').read_text(encoding='utf-8'))

    days = OrderedDict()
    for t in trades:
        d = days.setdefault(t['date'], {'n': 0, 'win': 0, 'profit': 0.0})
        d['n'] += 1
        d['win'] += t['profit'] > 0
        d['profit'] += t['profit']

    wins = [t['profit'] for t in trades if t['profit'] > 0]
    losses = [t['profit'] for t in trades if t['profit'] <= 0]
    total = sum(t['profit'] for t in trades)
    capital = capital_of(book)
    equity, peak, mdd = capital, capital, 0.0
    for d in days.values():
        equity += d['profit']
        peak = max(peak, equity)
        mdd = min(mdd, equity / peak - 1)

    out = []
    kind = '모의투자' if book.startswith('mock_') else '가상 매매'
    out.append(f'# {kind} 결과 — {book}\n')
    out.append(f'`python report.py`로 `data/{book}/`에서 자동 생성한 보고서입니다. '
               f'직접 고치지 말고, 메모는 [journal.md](journal.md)에 적습니다.\n')
    out.append(f'생성 시각: {datetime.now():%Y-%m-%d %H:%M}\n')

    out.append('## 요약\n')
    out.append('| 항목 | 값 |\n|---|---|')
    out.append(f'| 기간 | {", ".join(days) if len(days) <= 3 else f"{next(iter(days))} ~ {list(days)[-1]}"} ({len(days)}거래일) |')
    out.append(f'| 시작 자금 | {capital:,}원 |')
    out.append(f'| 현재 현금 | {state["cash"]:,.0f}원 |')
    out.append(f'| 누적 실현손익 | {won(total)}원 ({total / capital * 100:+.2f}%) |')
    out.append(f'| 거래 수 | {len(trades)}건 (이익 {len(wins)}, 손실 {len(losses)}) |')
    if trades:
        out.append(f'| 승률 | {len(wins) / len(trades) * 100:.1f}% |')
        out.append(f'| 평균 이익 / 평균 손실 | {won(sum(wins) / len(wins)) if wins else "-"}원 / '
                   f'{won(sum(losses) / len(losses)) if losses else "-"}원 |')
        best = max(trades, key=lambda t: t['profit'])
        worst = min(trades, key=lambda t: t['profit'])
        out.append(f'| 최대 이익 거래 | {best["name"]} {won(best["profit"])}원 ({best["rate"]:+.2f}%) |')
        out.append(f'| 최대 손실 거래 | {worst["name"]} {won(worst["profit"])}원 ({worst["rate"]:+.2f}%) |')
        out.append(f'| 비용 합계 (수수료, 세금) | {sum(t["cost"] for t in trades):,.0f}원 |')
    out.append(f'| 최대 낙폭 (일 단위) | {mdd * 100:.2f}% |')
    if still_open:
        out.append(f'| 미청산 | {", ".join(b["name"] for b in still_open.values())} |')
    out.append('')

    out.append('## 일별 결과\n')
    out.append('| 날짜 | 거래 | 이익/손실 | 실현손익 | 누적 손익 |\n|---|---|---|---|---|')
    cum = 0.0
    for date, d in days.items():
        cum += d['profit']
        out.append(f'| {date} | {d["n"]}건 | {d["win"]}/{d["n"] - d["win"]} | '
                   f'{won(d["profit"])}원 | {won(cum)}원 |')
    out.append('')

    out.append('## 거래 내역\n')
    out.append('| 날짜 | 버전 | 종목 | 매수 | 매도 | 보유 | 매수 신호 | 매입가 | 매도가 | 수량 | 손익 | 수익률 | 매도 사유 |')
    out.append('|---|---|---|---|---|---|---|---|---|---|---|---|---|')
    for t in trades:
        out.append(f'| {t["date"]} | {t["version"] or "-"} | {t["name"]}({t["code"]}) | {t["buy_time"]} | {t["sell_time"]} | '
                   f'{t["hold"]} | {t["signal"]} | {t["buy_price"]:,.0f} | {t["sell_price"]:,.0f} | '
                   f'{t["qty"]:,} | {won(t["profit"])} | {t["rate"]:+.2f}% | {t["sell_reason"]} |')
    out.append('')
    out.append('매입가와 매도가는 체결 가격 차이(SLIPPAGE)를 반영한 가상 체결가이고, '
               '손익은 수수료와 매도 세금을 뺀 값입니다.\n')
    return '\n'.join(out)


# ---------------------------------------------------------------- quantstats 성과 분석
MIN_DAYS = 5            # 거래일이 이보다 적으면 분석 보고서를 만들지 않음 (숫자에 의미가 없음)
BENCH_FILE = DATA_ROOT / 'research' / 'intraday' / '069500_1d.csv'   # tools/fetch_research_data.py가 받음


def daily_returns(book):
    """매도로 실현된 손익을 날짜별로 모아 일별 수익률로 (그날 시작 자산 대비). 거래 없는 평일은 0"""
    import pandas as pd
    rows = [r for r in read_trades(DATA_ROOT / book / 'trades.csv') if r['side'] == 'SELL']
    if not rows:
        return None
    pnl = pd.Series([float(r['profit'] or 0) for r in rows],
                    index=pd.to_datetime([r['time'][:10] for r in rows])).groupby(level=0).sum()
    days = pd.bdate_range(pnl.index.min(), max(pnl.index.max(), pd.Timestamp(datetime.now().date())))
    pnl = pnl.reindex(days, fill_value=0.0)
    start_equity = capital_of(book) + pnl.cumsum().shift(1, fill_value=0.0)
    return (pnl / start_equity).rename(book)


def benchmark(index):
    """KODEX 200 일별 수익률. 받아 둔 파일이 없으면 None"""
    import pandas as pd
    if not BENCH_FILE.exists():
        return None
    d = pd.read_csv(BENCH_FILE, index_col=0)
    d.index = pd.to_datetime(d.index, utc=True).tz_convert('Asia/Seoul').tz_localize(None).normalize()
    r = d['Close'].pct_change().rename('KODEX 200')
    return r.reindex(index).fillna(0.0)


def quantstats_reports(books):
    try:
        import quantstats as qs
        import pandas as pd
    except ImportError:
        print('quantstats가 없어 성과 분석은 건너뜁니다 (pip install quantstats)')
        return
    table = {}
    for book in books:
        r = daily_returns(book)
        if r is None or len(r) < MIN_DAYS:
            print(f'{book} : 거래일 {0 if r is None else len(r)}일, {MIN_DAYS}일 이상 쌓이면 성과 분석 보고서를 만듭니다')
            continue
        bench = benchmark(r.index)
        path = RESULTS_DIR / f'{book}_tearsheet.html'
        try:
            qs.reports.html(r, benchmark=bench, output=str(path), title=book,
                            download_filename=path.name)
            print(f'{path.relative_to(ROOT)} 생성' + ('' if bench is not None else ' (KODEX 200 비교 없음: tools/fetch_research_data.py 실행 필요)'))
        except Exception as ex:                     # 보고서 그림 문제로 전체가 멈추지 않게
            print(f'{book} 성과 분석 보고서 실패 : {ex}')
        table[book] = r
    if not table:
        return
    df = pd.DataFrame(table).fillna(0.0)
    bench = benchmark(df.index)
    if bench is not None:
        df['KODEX 200 (보유)'] = bench
    lines = ['# 장부 비교\n', f'`python report.py`로 생성. 생성 시각 {datetime.now():%Y-%m-%d %H:%M}\n',
             '일별 수익률은 매도로 실현된 손익 기준 (보유 중인 종목의 평가손익은 빠짐).\n',
             '| 항목 | ' + ' | '.join(df.columns) + ' |', '|---|' + '---|' * len(df.columns)]
    stats = {
        '기간(거래일)': lambda x: f'{len(x)}',
        '누적 수익률': lambda x: f'{qs.stats.comp(x):+.2%}',
        '연 환산 수익률': lambda x: f'{qs.stats.cagr(x, periods=252):+.1%}',
        '샤프 비율': lambda x: f'{qs.stats.sharpe(x, periods=252):.2f}',
        '소르티노 비율': lambda x: f'{qs.stats.sortino(x, periods=252):.2f}',
        '최대 낙폭': lambda x: f'{qs.stats.max_drawdown(x):.2%}',
        '이익 본 날 비율': lambda x: f'{qs.stats.win_rate(x):.0%}',
        '하루 최대 손실': lambda x: f'{x.min():+.2%}',
    }
    for name, f in stats.items():
        vals = []
        for c in df.columns:
            try:
                vals.append(f(df[c]))
            except Exception:
                vals.append('-')
        lines.append(f'| {name} | ' + ' | '.join(vals) + ' |')
    lines.append('\n거래일이 짧으면 연 환산 값과 비율은 크게 흔들립니다. 몇 주 이상 쌓인 뒤에 비교하세요.')
    (RESULTS_DIR / 'comparison.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('results/comparison.md 생성')


def main():
    RESULTS_DIR.mkdir(exist_ok=True)
    books = sorted(p.name for p in DATA_ROOT.iterdir()
                   if p.is_dir() and (p / 'trades.csv').exists()) if DATA_ROOT.exists() else []
    if not books:
        print('data 폴더에 매매 기록이 없습니다.')
        return
    for book in books:
        path = RESULTS_DIR / f'{book}.md'
        path.write_text(build(book), encoding='utf-8')
        print(f'{path.relative_to(ROOT)} 생성')
    quantstats_reports(books)


if __name__ == '__main__':
    main()
