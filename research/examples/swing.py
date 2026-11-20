"""스윙(7일 ~ 1개월 보유) 후보 시험 — 2026-11-20

    python -m research.examples.swing

후보는 결과를 보기 전에 정해 둔 6개뿐이다 (시험 횟수 기록용). 결과를 보고 숫자를 바꾸지 않는다.
교체 주기 5일(주 1회) 또는 10일(2주)로 보유 기간을 스윙에 맞춘다. 업종 중립은 3-3에서 효과가 있어 모두 켠다.
평균 보유일은 범위 200, 20종목, 탐색 구간 기준.
결과 (모두 탈락): docs/backtest_summary.md 9절
"""
from research.data import load_panel
from research.engine import backtest
from research.evaluate import SEARCH, judge
from research import factors as f

CANDIDATES = [
    ('단기 반전 1주, 주 1회 교체', lambda p: f.reversal(p, 5), 5),
    ('단기 반전 1개월, 주 1회 교체', lambda p: f.reversal(p, 21), 5),
    ('저변동성 + 단기 반전 1주, 주 1회 교체', lambda p: f.combine(f.low_volatility(p, 250), f.reversal(p, 5)), 5),
    ('모멘텀 + 저변동성 + 단기 반전 1주 (눌림목), 주 1회 교체',
     lambda p: f.combine(f.momentum(p, 12, 1), f.low_volatility(p, 250), f.reversal(p, 5)), 5),
    ('모멘텀 + 저변동성, 2주 교체', lambda p: f.combine(f.momentum(p, 12, 1), f.low_volatility(p, 250)), 10),
    ('52주 고가 근접 + 저변동성, 2주 교체', lambda p: f.combine(f.high52(p), f.low_volatility(p, 250)), 10),
]


def hold_days(p, score, every):
    t = backtest(p, score, *SEARCH, size=200, n=20, every=every, neutral=True).trades
    days = [(p.dates.get_loc(s) - p.dates.get_loc(b)) for b, s in zip(t['buy'], t['sell'])]
    return sum(days) / len(days) if days else 0


if __name__ == '__main__':
    p = load_panel('2010-06-01')
    for name, make, every in CANDIDATES:
        score = make(p)
        judge(p, score, name=name, neutral=True, every=every)
        print(f'평균 보유 {hold_days(p, score, every):.0f}거래일')
