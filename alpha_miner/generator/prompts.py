"""GPT에게 보낼 프롬프트

시장 이름·기간·날짜는 알려 주지 않는다 (모델이 학습한 시장 기억에 기대는 것을 줄이려고).
"""
from alpha_miner.data.loader import PRICE
from alpha_miner.engine.ast_parser import MAX_LENGTH, MAX_NODES, MAX_WINDOW

SYSTEM = f"""You design formulaic stock alpha factors for a cross-sectional long-only strategy.
Each day the strategy ranks the 200 largest stocks by your formula, holds the top 20, and rebalances every 10 trading days.
Only the top 20 names matter. A formula is first judged by how much the next 10-day return of its top 20 names
(equal weight) beats the cap-weighted market index, after round-trip cost (about 0.33%) on the names replaced at each
rebalance; then by a backtest. The index is dominated by a few very large stocks, so in some years the average stock
lags it badly; beating the average of the 200 stocks is not enough.
A good rank correlation over the whole cross-section is not enough: the very top names (often recent spikes or
speculative themes) can be the worst performers, so make sure the highest scores go to names you would actually want to hold.
Higher formula value must mean "expected to outperform"; the evaluator also tests the opposite sign, so a strong negative signal is fine.

Grammar (anything else is rejected):
- price/volume features (daily, split-adjusted): {', '.join(PRICE)}  (amount = traded value, mcap = market cap)
- fundamental/flow features (published monthly, constant within the month, start one year later than prices):
  per, pbr (price/earnings, price/book; missing when not meaningful such as losses), div (dividend yield %),
  foreign, institution (net buying value by foreign / institutional investors over the last month),
  foreign3, institution3 (same over the last 3 months). Scale flows by mcap or amount before comparing stocks.
- binary operators: + - * /     unary: -
- functions: abs(x), log(x), sign(x),
  ts_delay(x, d), ts_delta(x, d), ts_mean(x, d), ts_std(x, d), ts_min(x, d), ts_max(x, d), ts_rank(x, d), ts_corr(x, y, d),
  cs_rank(x), cs_zscore(x), cs_demean(x)
- d must be an integer literal, 1..{MAX_WINDOW} (ts_std, ts_rank >= 2; ts_corr >= 3)
- at most {MAX_LENGTH} characters and {MAX_NODES} syntax nodes; no keyword arguments, no other functions
Price levels differ across stocks, so compare prices as ratios or returns, not raw levels.
Prefer signals that change slowly (low turnover) and have an economic rationale you can state in one sentence."""


FOCUS = {
    # 15절: 가장 가까웠던 계열 (가격-거래량 상관). 창 길이만 바꾸지 말고 구조를 바꿔 다듬게 한다
    'pv': """Focus: the price-volume correlation family has been the closest so far (e.g. ts_corr(close, volume, 30),
-ts_corr(returns, ts_mean(volume,20)/mcap, 30)); its IC is consistent but slightly too weak.
Refine this family by changing its structure, for example: correlate different price measures (returns, close/vwap,
(high-low)/vwap, intraday move (close-open)/open) with different volume measures (volume, amount/mcap, volume relative
to its own average); condition or scale the correlation by volatility, liquidity or recent return; combine two
different price-volume correlations; smooth the signal to lower turnover. Each formula must state why it should work.""",
}


def user_message(n, best, recent, focus=None):
    """best: 지금까지 IC가 높았던 후보, recent: 지난 라운드 결과 (오류·탈락 이유 포함), focus: FOCUS 키"""
    lines = ([FOCUS[focus], ''] if focus else []) + [
             f'Propose {n} new formulas that differ from the ones below.',
             'Do not resubmit a failed idea with only different window lengths or a different scaling; try a different idea.',
             'A formula passes the first gate only if its top-20 return over the index after cost is positive in two separate periods.']
    if best:
        lines.append('\nBest so far (top-20 10-day return over the index after cost in period A / period B, '
                     '10-day rank IC A / B, daily turnover of the top 20, outcome):')
        lines += [f"- {r['formula']}  excess {r['ex_a']:+.2%} / {r['ex_b']:+.2%}, IC {r['ic_a']:+.3f} / {r['ic_b']:+.3f}, "
                  f"turnover {r['turnover']:.0%}, {r['status']}: {r.get('reason', '')}" for r in best]
    if recent:
        lines.append('\nLast round:')
        lines += [f"- {r['formula']}  -> {r['status']}: {r.get('reason', '')}" for r in recent]
    return '\n'.join(lines)
