"""알파 마이너 v0 1단계: 수식 → 피처 → IC·회전율 파이프라인이 제대로 도는지 확인 (LLM 없이)

    python -m alpha_miner.main ["수식" ...]

마이너는 탐색 구간(2012 ~ 2019)까지만 불러온다. 검증 구간(2020 ~ 2024)과 2025년 이후는 이 모듈에서 보지 않는다.
참고 문턱 (docs/backtest_summary.md 12·13절, 시가총액 상위 200 안 IC):
    10일 교체 + 하락 국면 50%: 10일 IC 약 0.04 이상 (아슬아슬) / 월 교체: 약 0.066 이상
"""
import sys

from alpha_miner.data.loader import load
from alpha_miner.engine.ast_parser import AlphaASTParser, AlphaSyntaxError
from alpha_miner.evaluation.metrics import summary, table

START, END = '2010-06-01', '2019-12-31'           # 피처 계산용으로 앞을 조금 더 불러옴
SEARCH = ('2012-01-01', '2019-12-31')
DEFAULT = ['-ts_delta(close, 5)', 'ts_corr(close, volume, 10)']

if __name__ == '__main__':
    formulas = sys.argv[1:] or DEFAULT
    p, feats = load(START, END)
    parser = AlphaASTParser(feats)
    rows = []
    for expr in formulas:
        try:
            score = parser.evaluate(expr).loc[SEARCH[0]:SEARCH[1]]
        except AlphaSyntaxError as e:
            rows.append({'수식': expr, '오류': str(e)})
            continue
        rows.append({'수식': expr, **summary(p, score.reindex(p.dates))})
    print(table(rows).to_string(index=False))
