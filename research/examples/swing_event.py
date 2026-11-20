"""이벤트 진입 + 개별 청산 스윙 후보 시험 — 2026-11-20

    python -m research.examples.swing_event

research/engine.py는 정기 교체를 가정해서 이 파일 안에서 따로 흉내 낸다 (엔진은 고치지 않음).
후보는 결과를 보기 전에 정한 3개뿐이다. 결과를 보고 숫자를 바꾸지 않는다.
2025년 이후는 불러오지도 않는다 (통과 전까지 봉인).
결과 (모두 탈락): docs/backtest_summary.md 10절

공통 규칙 (미리 고정)
    가격      : 수정 가격 (p.idx와 같은 날의 수정 계수로 시가·고가·저가도 맞춤). 거래량도 같은 계수로 나눔
    종목 범위 : 그날 시가총액 상위 150·200·300 (보통주, 20일 평균 거래대금 10억 이상). 세 범위의 중앙값으로 판정
    진입      : 그날 종가로 신호 → 다음 거래일 시가에 매수. 신호가 빈자리보다 많으면 시가총액 큰 순
    자금      : 최대 5종목, 종목당 그때 자산의 20%. 정기 교체 없음. 보유 중인 종목은 다시 사지 않음
    청산 순서 : 같은 날 손절과 익절이 둘 다 닿으면 손절로 본다 (보수적)
                손절 = 매수 시가 -5%. 시가가 이미 그 아래면 시가에, 아니면 손절가에
                익절 = 매수 시가 +10% 또는 +15%. 시가가 이미 그 위면 시가에, 아니면 익절가에
                그다음 종가 조건 (20일선 이탈, 타임컷)은 그날 종가에. 타임컷 = 매수일 포함 N거래일째 종가
    비용      : config의 수수료·슬리피지·매도세 (왕복 약 0.33%)
    거래 없는 날(거래량 0)에는 사지도 팔지도 않음. 상장폐지되면 마지막 종가에 판다
    판정      : evaluate.passes와 같은 기준 (탐색은 코스피 이상, 검증은 코스피 + 5%p 이상, 둘 다 낙폭은 코스피보다 작게)

후보
    1 추세 눌림목    : 20일선 > 60일선, 오늘까지 3 ~ 5일 연속 하락(6일 이상 연속은 제외),
                       최근 3일 평균 거래량 < 그 전 20일 평균, 종가가 20일선 ±2% 안
                       청산 +10% / -5% / 20거래일
    2 변동성 수축 돌파: 어제까지의 10일 ATR(종가 대비 %)이 지난 120일 중 하위 20% 안,
                       오늘 종가 > 지난 20일 최고 종가, 오늘 거래량 ≥ 지난 20일 평균의 2배
                       청산 +15% / -5% / 종가 20일선 아래 / 30거래일
    3 레짐 눌림목    : 코스피(직접 계산)가 60일선 위인 날만 후보 1 신호
                       청산은 후보 1과 같음
"""
import numpy as np
import pandas as pd

import config
from research.data import load_panel
from research.engine import stats_of
from research.evaluate import SEARCH, VALID, passes
from trader import marcap

N, SLOT = 5, 0.20
SIZES = (150, 200, 300)
FEE, SLIP, TAX = config.FEE_RATE, config.SLIPPAGE, config.STOCK_SELL_TAX
RULES = {                       # 이름: (신호, 익절, 손절, 최대 보유일, 20일선 이탈 청산)
    '후보 1 추세 눌림목': ('pullback', 0.10, 0.05, 20, False),
    '후보 2 변동성 수축 돌파': ('squeeze', 0.15, 0.05, 30, True),
    '후보 3 레짐 + 눌림목': ('regime', 0.10, 0.05, 20, False),
}


def simulate(days, O, H, L, C, V, MA20, SIG, PRI, tp, sl, max_days, ma_exit):
    """numpy 배열(날짜 × 종목)로 하루씩 돈다. 자산 곡선(list)과 거래 목록을 돌려준다"""
    cash, pos, pending, curve, trades = 1.0, {}, [], [], []

    def sell(c, px, t, why):
        nonlocal cash
        ps = pos.pop(c)
        cash += ps['units'] * px * (1 - SLIP) * (1 - FEE - TAX)
        cost = ps['ref'] * (1 + SLIP) * (1 + FEE)
        trades.append((px * (1 - SLIP) * (1 - FEE - TAX) / cost - 1, t - ps['t'] + 1, why))

    for t in days:
        for c in [c for c in pos if np.isnan(C[t, c])]:                  # 상장폐지
            sell(c, pos[c]['last'], t, '상장폐지')
        equity = cash + sum(ps['units'] * ps['last'] for ps in pos.values())
        for c in pending:                                                 # 어제 신호 → 오늘 시가 매수
            if len(pos) >= N:
                break
            if V[t, c] <= 0 or not O[t, c] > 0:
                continue
            amount = min(equity * SLOT, cash / (1 + FEE))
            if amount < equity * SLOT * 0.5:
                continue
            cash -= amount * (1 + FEE)
            pos[c] = {'t': t, 'ref': O[t, c], 'units': amount / (O[t, c] * (1 + SLIP)), 'last': O[t, c]}
        for c in list(pos):
            ps = pos[c]
            if V[t, c] <= 0 or np.isnan(C[t, c]):
                continue
            ps['last'] = C[t, c]
            stop, target = ps['ref'] * (1 - sl), ps['ref'] * (1 + tp)
            if O[t, c] <= stop:
                sell(c, O[t, c], t, '손절')
            elif L[t, c] <= stop:
                sell(c, stop, t, '손절')
            elif O[t, c] >= target:
                sell(c, O[t, c], t, '익절')
            elif H[t, c] >= target:
                sell(c, target, t, '익절')
            elif ma_exit and C[t, c] < MA20[t, c]:
                sell(c, C[t, c], t, '20일선 이탈')
            elif t - ps['t'] + 1 >= max_days:
                sell(c, C[t, c], t, '타임컷')
        free = N - len(pos)
        cand = [c for c in np.where(SIG[t])[0] if c not in pos]
        pending = sorted(cand, key=lambda c: -PRI[t, c])[:free] if free > 0 else []
        curve.append(cash + sum(ps['units'] * ps['last'] for ps in pos.values()))
    return curve, trades


def self_check():
    """장난감 자료로 청산 규칙 확인: 둘째 날 익절, 넷째 날 같은 날 익절·손절이면 손절"""
    o = np.array([[100.], [100.], [100.], [100.], [100.]])
    h = np.array([[100.], [111.], [100.], [111.], [100.]])
    lo = np.array([[100.], [99.], [100.], [94.], [100.]])
    c = np.full((5, 1), 100.)
    v = np.ones((5, 1))
    sig = np.array([[True], [False], [True], [False], [False]])
    _, tr = simulate(range(5), o, h, lo, c, v, c, sig, v, 0.10, 0.05, 20, False)
    assert [w for _, _, w in tr] == ['익절', '손절'], tr
    assert abs(tr[0][0] - (1.10 * (1 - SLIP) * (1 - FEE - TAX) / ((1 + SLIP) * (1 + FEE)) - 1)) < 1e-12
    _, tr = simulate(range(5), o, o, o, c, v, c, sig[:, :] & np.array([[True]] + [[False]] * 4), v,
                     0.10, 0.05, 3, False)
    assert tr == [(tr[0][0], 3, '타임컷')], tr                  # 매수일 포함 3거래일째 종가


def load_high_low(p):
    out = {}
    for col in ('High', 'Low'):
        parts = []
        for y in sorted({d.year for d in p.dates}):
            df = pd.read_parquet(marcap.path_of(y), columns=['Date', 'Code', col])
            df['Date'] = pd.to_datetime(df['Date'])
            df = df[df['Date'].isin(p.dates)].drop_duplicates(['Date', 'Code'])
            parts.append(df.pivot(index='Date', columns='Code', values=col).astype('float32'))
        out[col] = pd.concat(parts).sort_index().reindex(index=p.dates, columns=p.codes)
    return out['High'], out['Low']


def signals(p):
    """수정 가격과 후보별 신호표 (날짜 × 종목, bool)"""
    f = (p.idx / p.close).astype('float32')                     # 그날의 수정 계수
    C = p.idx.astype('float32')
    O = (p.open * f).where(p.open > 0)
    hi, lo = load_high_low(p)
    H, L = hi * f, lo * f
    V = p.volume / f
    ma20 = C.rolling(20, min_periods=20).mean()
    ma60 = C.rolling(60, min_periods=60).mean()

    down = C < C.shift(1)
    run3 = down & down.shift(1, fill_value=False) & down.shift(2, fill_value=False)
    run6 = run3 & down.shift(3, fill_value=False) & down.shift(4, fill_value=False) & down.shift(5, fill_value=False)
    quiet = V.rolling(3).mean() < V.shift(3).rolling(20).mean()
    near = (C / ma20 - 1).abs() <= 0.02
    pullback = (ma20 > ma60) & run3 & ~run6 & quiet & near

    pc = C.shift(1)
    tr = np.fmax(np.fmax(H - L, (H - pc).abs()), (L - pc).abs())
    atr = tr.rolling(10, min_periods=10).mean() / C
    low_atr = atr.rolling(120, min_periods=100).rank(pct=True).shift(1) <= 0.2
    breakout = C > C.shift(1).rolling(20, min_periods=20).max()
    loud = V >= 2 * V.shift(1).rolling(20, min_periods=15).mean()
    squeeze = low_atr & breakout & loud

    up = p.kospi > p.kospi.rolling(60, min_periods=60).mean()
    regime = pullback & pd.DataFrame(np.repeat(up.to_numpy()[:, None], len(p.codes), 1),
                                     index=p.dates, columns=p.codes)
    prices = {k: v.to_numpy(dtype='float64') for k, v in
              {'O': O, 'H': H, 'L': L, 'C': C, 'V': V, 'MA20': ma20}.items()}
    return prices, {'pullback': pullback.to_numpy(), 'squeeze': squeeze.to_numpy(), 'regime': regime.to_numpy()}


def universe(p, size):
    ok = p.eligible & (p.amount20 >= 1e9) & p.idx.notna() & p.mcap.notna()
    return (p.mcap.where(ok).rank(axis=1, ascending=False, method='first') <= size).to_numpy()


def main():
    self_check()
    p = load_panel('2011-01-01', VALID[1])                       # 2025년 이후는 불러오지 않음
    prices, sig = signals(p)
    univ = {s: universe(p, s) for s in SIZES}
    pri = p.mcap.fillna(0).to_numpy()
    for name, (key, tp, sl, max_days, ma_exit) in RULES.items():
        print(f'\n== {name}  (+{tp:.0%} / -{sl:.0%} / {max_days}거래일{", 20일선 이탈" if ma_exit else ""})')
        verdict = []
        for label, (a, b), extra in (('탐색', SEARCH, 0.0), ('검증', VALID, 0.05)):
            days = np.where((p.dates >= a) & (p.dates <= b))[0]
            k = stats_of(p.kospi.iloc[days])
            res = {}
            for s in SIZES:
                curve, trades = simulate(days, **prices, SIG=sig[key] & univ[s], PRI=pri,
                                         tp=tp, sl=sl, max_days=max_days, ma_exit=ma_exit)
                res[s] = (stats_of(pd.Series(curve, index=p.dates[days])), trades)
            med = {m: float(np.median([r[0][m] for r in res.values()])) for m in ('cagr', 'mdd', 'sharpe')}
            ok = passes(med, k, extra)
            verdict.append(ok)
            rets, held, why = zip(*res[200][1]) if res[200][1] else ((), (), ())
            whys = pd.Series(why).value_counts().to_dict() if why else {}
            print(f"{label} {a[:4]} ~ {b[:4]} : 중앙값 연 {med['cagr']:+.1%}, 낙폭 {med['mdd']:.0%}, "
                  f"샤프 {med['sharpe']:.2f} | 범위별 "
                  + ' / '.join(f"{res[s][0]['cagr']:+.1%}" for s in SIZES)
                  + f" | 코스피 {k['cagr']:+.1%}, 낙폭 {k['mdd']:.0%} | 통과 {'예' if ok else '아니요'}")
            if rets:
                print(f"    범위 200: 거래 {len(rets)}건, 승률 {np.mean(np.array(rets) > 0):.0%}, "
                      f"평균 {np.mean(rets):+.2%}, 평균 보유 {np.mean(held):.1f}거래일, 청산 {whys}")
        print('판정:', '통과' if all(verdict) else '탈락')


if __name__ == '__main__':
    main()
