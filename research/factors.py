"""자주 쓰는 점수 재료 (모두 날짜 × 종목 표, 클수록 "좋다"는 방향으로 맞춰 둠)

그날까지의 값으로만 계산한다. backtest()가 lag만큼 더 늦춰 쓴다.
"""
import numpy as np
import pandas as pd


# ---------------------------------------------------------------- 가격
def momentum(p, months=12, skip=1):
    """months개월 수익률, 최근 skip개월 제외 (12-1 모멘텀이 학계 표준)"""
    return p.idx.shift(21 * skip) / p.idx.shift(21 * months) - 1


def reversal(p, days=21):
    """최근 days일 수익률의 반대 (많이 빠진 종목이 높은 점수)"""
    return -(p.idx / p.idx.shift(days) - 1)


def low_volatility(p, days=250):
    """변동성이 낮을수록 높은 점수"""
    return -p.ret.rolling(days, min_periods=int(days * 0.6)).std()


def high52(p):
    """52주 최고가에 가까울수록 높은 점수"""
    return p.idx / p.idx.rolling(252, min_periods=200).max()


def small(p):
    """시가총액이 작을수록 높은 점수 (종목 범위 안에서)"""
    return -np.log(p.mcap)


def low_turnover(p):
    """거래대금 ÷ 시가총액이 낮을수록 높은 점수"""
    return -(p.amount20 / p.mcap)


# ---------------------------------------------------------------- DART 재무 (p.add_dart() 먼저)
def book_to_price(p):
    """PBR의 역수. 자본잠식은 가장 낮게"""
    e = p.dart['equity']
    return (e / p.mcap).where(e > 0, -1.0)


def earnings_yield(p):
    """최근 4분기 순이익 ÷ 시가총액"""
    return p.dart['ni_ttm'] / p.mcap


def roe(p):
    e = p.dart['equity']
    return (p.dart['ni_ttm'] / e).where(e > 0, -1.0)


def operating_profitability(p):
    """최근 4분기 영업이익 ÷ 자산"""
    return p.dart['op_ttm'] / p.dart['assets']


def low_leverage(p):
    return -(p.dart['liabilities'] / p.dart['assets'])


# ---------------------------------------------------------------- 거래소 수급·배당 (p.add_krx() 먼저)
def institution_selling(p, months=3):
    """기관이 많이 판 종목일수록 높은 점수 (2013 ~ 2024 5분위 차 연 -10.5%, t -2.96: 판 종목이 더 오름)"""
    key = 'institution3' if months == 3 else 'institution'
    return -(p.krx[key] / p.mcap.shift(1))


def foreign_selling(p, months=3):
    key = 'foreign3' if months == 3 else 'foreign'
    return -(p.krx[key] / p.mcap.shift(1))


def dividend_yield(p):
    return p.krx['div']


# ---------------------------------------------------------------- 섞기
def combine(*scores, weights=None):
    """여러 점수를 날짜마다 순위(0 ~ 1)로 바꿔 가중 평균. NaN이 하나라도 있으면 NaN"""
    weights = weights or [1.0] * len(scores)
    ranked = [s.rank(axis=1, pct=True) * w for s, w in zip(scores, weights)]
    total = ranked[0]
    for r in ranked[1:]:
        total = total + r
    return total / sum(weights)
