"""새 종목 선택 전략을 시험하는 틀 — 이 파일을 복사해서 make_score()만 바꾸면 된다

    python -m research.examples.factor_template

1. 데이터를 불러온다 (처음 한 번 1~2분)
2. make_score()에서 점수표를 만든다 (날짜 × 종목, 클수록 좋음)
3. judge()가 탐색·검증 구간, 6개 설정으로 돌려서 채택 기준 통과 여부를 알려 준다
"""
from research.data import load_panel
from research.evaluate import judge
from research import factors as f


def make_score(p):
    # 예시: 업종 중립 12-1 모멘텀 + 1년 저변동성 (2026-11-19 시험에서 근소하게 탈락했던 조합)
    return f.combine(f.momentum(p, 12, 1), f.low_volatility(p, 250))


if __name__ == '__main__':
    p = load_panel('2010-06-01')
    # 재무나 수급을 쓰려면: p.add_dart(), p.add_krx()
    score = make_score(p)
    judge(p, score, name='모멘텀 + 저변동성 (업종 중립)', neutral=True, every=21)
