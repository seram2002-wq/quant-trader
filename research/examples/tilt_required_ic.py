"""3단계 1a: 대장주 바구니 + 지수 기울이기 구조의 손익분기 IC — 2026-11-24
(가짜 신호 = 미래 수익률을 일부러 섞은 측정이라 후보가 아님)

    python -m research.examples.tilt_required_ic

구조 (2026-11-24 확정)
  S1 코어·위성   : 자금 c는 코스피 지수(KODEX 200 대용, 보수 연 0.15% 뺌), 1-c는 업종마다 신호 1등 종목에 똑같이 (c = 0.7, 0.5)
  S2 직접 기울이기: 바구니를 시가총액 비중 b로 들고, 업종마다 신호 꼴찌 비중 일부 Δ = min(k·b_꼴찌, 5%p)를 1등에게 (k = 0.5, 1.0)
  교체           : h거래일마다. 업종 1등(S1)·1등과 꼴찌(S2)가 바뀐 업종만 거래하고, 그대로면 지난 비중 유지
                   바구니 구성이 바뀌면(매월) S2와 기준 바구니의 들어오고 나간 종목도 거래
  하락 국면 장치 : 코스피 120일선 아래면 전체 비중 50%. 판정은 장치를 붙인 쪽으로
  바구니         : trader.basket.select를 2011-12 ~ 2024-12 매월 말 자료로 (다음 달 둘째 거래일부터)
가짜 신호: 업종 안 상대 수익(h일 미래 수익 - 같은 업종 평균)의 순위 + 잡음. 목표 IC 0(대조군), 0.03, 0.05, 0.08, 0.10, 시드 3개 중앙값
판정 (이 구조용, 실행 전 확정): 탐색 2012 ~ 2019, 검증 2020 ~ 2024 두 구간 모두
  ① 코스피 대비 연 초과 +2.0%p 이상  ② 정보비율(일별 초과 수익 기준) 0.5 이상  ③ 장치를 붙인 최대 낙폭이 코스피보다 작음
  ④ 신호 없는 같은 구조 대비 비용 뒤 연 +1.0%p 이상 ('명확한 플러스'의 기준값)
     신호 없는 구조: S1 = c·지수 + (1-c)·바구니 시가총액 비중, S2 = 바구니 시가총액 비중 (둘 다 장치 붙임)
     업종 분류가 지금 상장 종목만 있어 상장폐지 종목이 바구니에 못 들어가는 생존 편향을 걷어내는 비교
손익분기 IC = 판정을 통과하는 가장 작은 목표 IC (시드 중앙값). 0.04 이하면 마이너 재가동, 0.05 초과면 중단, 사이는 1b를 보고
shortcut: 기간 사이 비중은 고정(매일 맞춘 것과 같음, 그 비용은 안 셈). 바구니·S1 위성의 비중 흔들림 비용은 무시
2025년 이후는 불러오지 않는다. 결과: data/research/tilt_required_ic.csv
"""
import numpy as np
import pandas as pd

from research.data import RESEARCH, load_panel
from research.engine import stats_of
from research.examples.drawdown_overlay import BUY, MA, SELL, overlay
from research.examples.required_ic import LAG, forward
from trader import basket

START, END = '2011-06-01', '2024-12-31'
PERIODS = {'탐색': ('2012-01-01', '2019-12-31'), '검증': ('2020-01-01', '2024-12-31')}
LEVELS = (0.0, 0.03, 0.05, 0.08, 0.10)
HS = (5, 10, 21)
SEEDS = (0, 1, 2)
STRUCTS = (('S1', 0.7), ('S1', 0.5), ('S2', 0.5), ('S2', 1.0))
ETF_FEE, MAX_TILT, WEIGHT = 0.0015, 0.05, 0.5
HIST = RESEARCH / 'basket_history.csv'


def baskets(p):
    """[(적용 시작 위치, 바구니 표)] 기준일 순. 처음 한 번 만들어 data/research/basket_history.csv에 둔다"""
    if HIST.exists():
        h = pd.read_csv(HIST, dtype={'code': str}, parse_dates=['base'])
    else:
        h = basket.history('2011-12-01', END)
        h.to_csv(HIST, index=False, encoding='utf-8')
    return [(p.dates.searchsorted(base) + 2, g) for base, g in h.groupby('base')]


def plan(p, bs, h, score_at, fwd):
    """h거래일마다 [(T 위치, 종목, 업종, {업종: (1등, 꼴찌)})]와 진단 [(T, IC, 업종 안 1등-꼴찌 상대 수익)].
    T 종가에 비중을 맞추고, 점수는 T-LAG 날짜 것 (forward와 같은 시점 맞추기)"""
    first = max(p.dates.searchsorted(pd.Timestamp(PERIODS['탐색'][0])) - 1, bs[0][0])
    out, diag, k = [], [], 0
    for T in range(first, len(p.dates) - 1, h):
        while k + 1 < len(bs) and bs[k + 1][0] <= T:
            k += 1
        g = bs[k][1]
        s = T - LAG
        codes, sect = g['code'].tolist(), g.set_index('code')['sector']
        f = fwd.iloc[s].reindex(codes)
        rel = f - f.groupby(sect).transform('mean')
        score = score_at(s, codes, rel).where(rel.notna())
        ok = score.notna()
        roles = {sec: (x.idxmax(), x.idxmin()) for sec, x in score[ok].groupby(sect[ok])}
        if not roles:                                   # 점수가 하나도 없으면(자료 끝 등) 지난 비중 유지
            continue
        out.append((T, codes, sect, roles))
        if ok.sum() >= 5:
            spread = np.mean([rel[t] - rel[b] for t, b in roles.values() if t != b] or [np.nan])
            diag.append((T, score[ok].rank().corr(rel[ok].rank()), spread))
    return out, diag


def simulate(p, steps, kind, x, R, mc, core):
    """(전략 일별 수익, 신호 없는 같은 구조의 일별 수익) numpy 배열 (p.dates 길이)"""
    n = len(p.dates)
    strat, base = np.zeros(n), np.zeros(n)
    prev_roles, tilt, prev_b = {}, {}, {}
    for i, (T, codes, sect, roles) in enumerate(steps):
        end = steps[i + 1][0] if i + 1 < len(steps) else n - 1
        seg = slice(T + 1, end + 1)
        cols = [p.col[c] for c in codes]
        r = np.nan_to_num(R[seg][:, cols])                               # 상장폐지 뒤는 마지막 가격 (수익 0)
        w = np.nan_to_num(mc[T:end][:, cols])                            # 전날 시가총액 비중
        bret = np.nan_to_num((w * r).sum(axis=1) / w.sum(axis=1))
        b = dict(zip(codes, np.nan_to_num(mc[T][cols]) / np.nansum(mc[T][cols])))
        member_cost = (sum(v for c, v in b.items() if c not in prev_b) * BUY
                       + sum(v for c, v in prev_b.items() if c not in b) * SELL)
        if kind == 'S1':
            tops = [t for t, _ in roles.values()]
            sat = r[:, [codes.index(t) for t in tops]].mean(axis=1)
            strat[seg] = x * core[seg] + (1 - x) * sat
            changed = sum(1 for sec, (t, _) in roles.items() if prev_roles.get(sec, (None,))[0] != t)
            cost = (1 - x) * changed / len(tops) * (BUY + (SELL if prev_roles else 0))
            base[seg] = x * core[seg] + (1 - x) * bret
            bcost = (1 - x) * member_cost
        else:
            new = {c: v for c, v in tilt.items() if c in b and sect.get(c) in roles}
            for sec, (t, bot) in roles.items():
                if prev_roles.get(sec) == (t, bot) and (t == bot or (t in new and bot in new)):
                    continue                                                 # 1등·꼴찌 그대로 → 거래 없음
                for c in [c for c in new if sect.get(c) == sec]:
                    new.pop(c)
                if t != bot:
                    d = min(x * b[bot], MAX_TILT)
                    new[t], new[bot] = d, -d
            dt = {c: new.get(c, 0.0) - tilt.get(c, 0.0) for c in set(new) | set(tilt)}
            cost = member_cost + sum(v * BUY if v > 0 else -v * SELL for v in dt.values())
            tvec = np.array([new.get(c, 0.0) for c in codes])
            strat[seg] = bret + np.nan_to_num(r) @ tvec
            base[seg], bcost, tilt = bret, member_cost, new
        strat[T + 1] -= cost
        base[T + 1] -= bcost
        prev_roles, prev_b = roles, b
    return strat, base


def evaluate(p, strat, base, down, a, b):
    idx = p.dates[(p.dates >= a) & (p.dates <= b)]
    pos = p.dates.get_indexer(idx)
    eq = pd.Series(np.cumprod(1 + strat[pos]), index=idx)
    beq = pd.Series(np.cumprod(1 + base[pos]), index=idx)
    k = p.kospi.loc[idx]
    ov, bov = overlay(eq, down.loc[idx], WEIGHT), overlay(beq, down.loc[idx], WEIGHT)
    s, bs, ks, raw = stats_of(ov), stats_of(bov), stats_of(k), stats_of(eq)
    d = (ov.pct_change() - k.pct_change()).dropna()
    ir = d.mean() * 252 / (d.std() * np.sqrt(252)) if d.std() > 0 else 0.0
    out = {'초과': s['cagr'] - ks['cagr'], 'IR': ir, '낙폭': s['mdd'], '코스피 낙폭': ks['mdd'],
           '기준 대비': s['cagr'] - bs['cagr'], '장치 없음 초과': raw['cagr'] - ks['cagr']}
    out['통과'] = out['초과'] >= 0.02 and ir >= 0.5 and s['mdd'] > ks['mdd'] and out['기준 대비'] >= 0.01
    return out


def setup(p):
    p.col = {c: i for i, c in enumerate(p.codes)}
    R = p.ret.reindex(columns=p.codes).to_numpy(dtype='float64')
    mc = p.mcap.reindex(columns=p.codes).to_numpy(dtype='float64')
    core = (p.kospi.pct_change().fillna(0) - ETF_FEE / 252).to_numpy()
    down = p.kospi < p.kospi.rolling(MA, min_periods=MA).mean()
    return R, mc, core, down


def synthetic_score(ic, rng):
    a = ic / np.sqrt(1 - ic ** 2)

    def score_at(s, codes, rel):
        u = rel.rank()
        u = (u - u.mean()) / u.std()
        return a * u + pd.Series(rng.standard_normal(len(codes)), index=codes)
    return score_at


if __name__ == '__main__':
    p = load_panel(START, END)                                   # 2025년 이후는 불러오지 않음
    bs = baskets(p)
    R, mc, core, down = setup(p)
    rows = []
    for h in HS:
        fwd = forward(p, h)
        for ic in LEVELS:
            for seed in SEEDS:
                steps, diag = plan(p, bs, h, synthetic_score(ic, np.random.default_rng(seed)), fwd)
                real_ic, spread = np.nanmean([x[1] for x in diag]), np.nanmean([x[2] for x in diag])
                for kind, x in STRUCTS:
                    strat, base = simulate(p, steps, kind, x, R, mc, core)
                    for label, (a, b) in PERIODS.items():
                        rows.append({'h': h, '목표 IC': ic, 'seed': seed, '구조': f'{kind} {x}', '구간': label,
                                     '실제 IC': real_ic, '1등-꼴찌': spread,
                                     **evaluate(p, strat, base, down, a, b)})
            print(f'h {h}, IC {ic} 끝', flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(RESEARCH / 'tilt_required_ic.csv', index=False, encoding='utf-8')
    med = df.groupby(['구조', 'h', '목표 IC', '구간']).median(numeric_only=True).drop(columns='seed')
    med['통과'] = df.groupby(['구조', 'h', '목표 IC', '구간'])['통과'].mean() >= 0.5
    pd.set_option('display.width', 250)
    print(med.round(4).to_string())
    both = med['통과'].groupby(['구조', 'h', '목표 IC']).all()
    print('\n== 손익분기 IC (두 구간 모두 통과하는 가장 작은 목표 IC)')
    for (kind, h), g in both.groupby(['구조', 'h']):
        ok = g[g].index.get_level_values('목표 IC')
        print(f'{kind} h={h}: {min(ok) if len(ok) else "0.10에서도 미통과"}')
