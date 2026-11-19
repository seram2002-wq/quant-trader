"""멀티팩터 (하루 한 번 종목 교체, 다음 날까지 보유) — 가상 장부 실험 전략

장 마감 직전에 거래가 많은 종목들을 세 가지 기준으로 점수를 매겨 상위 종목을 사고,
다음 날 같은 시각에 다시 점수를 매겨 순위가 많이 밀린 종목만 바꾼다.

점수 (종목 범위 안에서 순위를 0~1로 바꾼 뒤 가중 합산)
    모멘텀 40% : 최근 20일 수익률 ÷ 같은 기간 하루 수익률의 표준편차
                 (변동성으로 나눈 모멘텀. 많이 흔들리며 오른 종목보다 꾸준히 오른 종목을 높게)
    수급   35% : 최근 5일 외국인 순매수 금액 ÷ 20일 평균 거래대금
                 (기관 순매수는 일별 시세 API에 없어서 외국인만. 값이 없으면 이 항목을 빼고 계산)
    반전   25% : 최근 3일 수익률의 반대 부호 (며칠 새 급등한 종목 추격 매수를 피함)

v0 규칙 (2026-11-18, 실험용. 가중치와 숫자는 근거가 아니라 출발점이며 백테스트로 정할 것)
    종목 범위 : 코스피·코스닥 거래대금 상위 각 30개 + 지금 보유 종목
                ETF·ETN, 우선주, 스팩 제외. 20일 평균 거래대금 50억 원 미만 제외
    국면      : KODEX 200이 20일 이동평균 위면 최대 5종목, 아래면 최대 2종목
                (한 번에 전부 팔고 사는 것보다 손바뀜과 세금이 적다)
    교체      : 15:05에 점수를 다시 매긴다
                보유 종목은 10위 안이면 계속 보유, 밖으로 밀리면 매도
                빈자리는 5위 안의 종목으로 채운다 (관리종목, 투자경고 이상은 사지 않음)
    보유      : 15:15 일괄 매도를 하지 않고 다음 날까지 들고 간다
    자금      : 종목마다 같은 금액 (config.py의 budget)
"""
import statistics

from strategies.base import Strategy
from trader.symbols import is_etf

TOP_N = 5                       # 새로 살 때: 이 순위 안의 종목만
HOLD_RANK = 10                  # 보유 종목: 이 순위 안이면 계속 보유
BEAR_SLOTS = 2                  # 약세 국면의 최대 보유 종목 수
MIN_VALUE = 5_000_000_000       # 20일 평균 거래대금 하한 (원)
WEIGHTS = {'mom': 0.40, 'flow': 0.35, 'rev': 0.25}
MOM_DAYS, FLOW_DAYS, REV_DAYS = 20, 5, 3
INDEX_CODE, INDEX_NAME, MA_DAYS = '069500', 'KODEX 200', 20
MARKETS = {'0001': '코스피', '1001': '코스닥'}
BAD_STATUS = {'51', '52', '53', '58'}   # 관리종목, 투자위험, 투자경고, 거래정지
BAD_WARN = {'02', '03'}                 # 투자경고, 투자위험


def is_excluded(name):
    """ETF·ETN, 우선주, 스팩"""
    n = (name or '').strip()
    return is_etf(n) or '스팩' in n or n.endswith(('우', '우B', '우C')) or '(전환)' in n


def pct_rank(values):
    """{code: 값} → {code: 0~1 순위}. 값이 클수록 1에 가깝다"""
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    return {code: (i / (n - 1) if n > 1 else 1.0) for i, (code, _) in enumerate(items)}


def factors(rows):
    """일별 시세(최신이 맨 앞)로 점수 재료를 계산. 기간이 모자라면 None"""
    if len(rows) < MOM_DAYS + 1:
        return None
    close = [r['close'] for r in rows]
    if min(close[:MOM_DAYS + 1]) <= 0:
        return None
    daily = [close[i] / close[i + 1] - 1 for i in range(MOM_DAYS)]
    vol = statistics.pstdev(daily)
    value = statistics.mean(r['close'] * r['volume'] for r in rows[:MOM_DAYS])
    foreign = sum(r.get('foreign', 0) * r['close'] for r in rows[:FLOW_DAYS])
    return {
        'price': close[0],
        'ret20': close[0] / close[MOM_DAYS] - 1,
        'mom': (close[0] / close[MOM_DAYS] - 1) / vol if vol > 0 else 0.0,
        'rev': -(close[0] / close[REV_DAYS] - 1),
        'flow': foreign / value if value > 0 else 0.0,
        'has_flow': any(r.get('foreign') for r in rows[:FLOW_DAYS]),
        'value': value,
    }


class MultiFactor(Strategy):
    name = '멀티팩터'
    VERSION = 'v0'
    buy_window = (1505, 1515)
    intraday_exit = False
    rebalance_time = 1505
    hold_overnight = True

    def universe(self, client):
        found = {}
        for market in MARKETS:
            for r in client.get_trade_value_rank(market):
                if not is_excluded(r['name']):
                    found.setdefault(r['code'], (r['name'], 'stock'))
        return found, '코스피·코스닥 거래대금 상위, ETF·우선주·스팩 제외'

    def regime(self, client):
        """(강세 여부, 설명)"""
        close = [r['close'] for r in client.get_ohlc(INDEX_CODE)]
        if len(close) < MA_DAYS:
            return True, f'{INDEX_NAME} 시세 부족, 강세로 간주'
        ma = statistics.mean(close[:MA_DAYS])
        bull = close[0] > ma
        return bull, (f'{INDEX_NAME} {close[0]:,} / {MA_DAYS}일 평균 {ma:,.0f} → '
                      f'{"강세" if bull else "약세"}')

    def score(self, client, holdings):
        """종목별 점수표 [(code, name, f, score)] 점수 높은 순, 제외 사유 {name: 사유}"""
        symbols, _ = self.universe(client)
        for code, p in holdings.items():
            symbols.setdefault(code, (p.get('name', code), p.get('kind', 'stock')))
        table, skipped = {}, {}
        for code, (name, _) in symbols.items():
            f = factors(client.get_ohlc(code))
            if f is None:
                skipped[name] = '시세 기간 부족'
            elif f['value'] < MIN_VALUE:
                skipped[name] = f'20일 평균 거래대금 {f["value"] / 1e8:,.0f}억'
            else:
                table[code] = (name, f)
        weights = dict(WEIGHTS)
        if not any(f['has_flow'] for _, f in table.values()):
            weights.pop('flow')                         # 외국인 순매수 값이 안 오면 수급 항목 제외
        total = sum(weights.values())
        ranks = {k: pct_rank({c: f[k] for c, (_, f) in table.items()}) for k in weights}
        scored = [(c, n, f, sum(w * ranks[k][c] for k, w in weights.items()) / total)
                  for c, (n, f) in table.items()]
        scored.sort(key=lambda x: x[3], reverse=True)
        return scored, skipped, weights

    def buyable(self, client, code):
        """관리종목, 투자경고 이상, 거래정지면 사유, 아니면 None"""
        q = client.get_price(code)
        if q.get('status') in BAD_STATUS or q.get('warn') in BAD_WARN:
            return f'종목 상태 {q.get("status")}/{q.get("warn")}'
        return None

    def targets(self, client, holdings, max_positions):
        """오늘 들고 갈 종목 [{'code','name','kind','reason'}]과 보고 문자열"""
        bull, regime_text = self.regime(client)
        slots = max_positions if bull else min(BEAR_SLOTS, max_positions)
        scored, skipped, weights = self.score(client, holdings)
        rank = {c: i + 1 for i, (c, *_rest) in enumerate(scored)}

        def reason(c):
            return f'{rank[c]}위, 점수 {scored[rank[c] - 1][3]:.2f}'

        keep = sorted((c for c in holdings if rank.get(c, 999) <= HOLD_RANK), key=rank.get)[:slots]
        chosen = [{'code': c, 'name': holdings[c].get('name', c), 'kind': 'stock',
                   'reason': reason(c)} for c in keep]
        blocked = {}
        for c, n, f, s in scored[:TOP_N]:
            if len(chosen) >= slots:
                break
            if c in keep:
                continue
            why = self.buyable(client, c)
            if why:
                blocked[n] = why
                continue
            chosen.append({'code': c, 'name': n, 'kind': 'stock', 'reason': reason(c)})

        used = ', '.join(f'{k} {w:.0%}' for k, w in weights.items())
        lines = [f'종목 교체 : {regime_text}, 최대 {slots}종목 (점수 {used})',
                 f'점수 상위 ({len(scored)}개 중):']
        for c, n, f, s in scored[:HOLD_RANK]:
            mark = '보유' if c in keep else ('매수' if any(t['code'] == c for t in chosen) else '')
            lines.append(f'  {rank[c]:>2}. {n}({c}) 점수 {s:.2f}, 20일 {f["ret20"]:+.1%}, '
                         f'3일 {-f["rev"]:+.1%}, 외국인 {f["flow"]:+.2f}  {mark}')
        if blocked:
            lines.append('매수 제외 : ' + ', '.join(f'{n}({w})' for n, w in blocked.items()))
        if skipped:
            lines.append(f'점수 제외 {len(skipped)}개 : '
                         + ', '.join(f'{n}({w})' for n, w in list(skipped.items())[:5])
                         + (' ...' if len(skipped) > 5 else ''))
        return chosen, '\n'.join(lines)
