"""벡터화 연산자. 모든 입력·출력은 index=날짜, columns=종목코드인 2D DataFrame

ts_ 연산자는 과거 d일만 본다 (미래 참조 없음). cs_ 연산자는 같은 날짜의 종목끼리만 비교한다.
창 길이(d)가 올바른지는 ast_parser가 미리 확인한다 (정수 상수, 범위 안).
"""
import numpy as np
import pandas as pd


class AlphaOperators:
    EPS = 1e-8

    # ------------------------------------------------------------ 안전 산술
    @classmethod
    def add(cls, x, y):
        return x + y

    @classmethod
    def sub(cls, x, y):
        return x - y

    @classmethod
    def mul(cls, x, y):
        return x * y

    @classmethod
    def div(cls, x, y):
        """0에 가까운 분모는 NaN (inf가 퍼지지 않게)"""
        if isinstance(y, pd.DataFrame):
            return x / y.where(y.abs() > cls.EPS, np.nan)
        if abs(y) <= cls.EPS:
            return x * np.nan
        return x / y

    @classmethod
    def abs(cls, x):
        return x.abs()

    @classmethod
    def log(cls, x):
        """0 이하는 NaN"""
        return np.log(x.where(x > cls.EPS, np.nan))

    @classmethod
    def sign(cls, x):
        return np.sign(x)

    # ------------------------------------------------------------ 시계열 (과거 d일)
    @staticmethod
    def ts_delay(x, d=1):
        return x.shift(int(d))

    @staticmethod
    def ts_delta(x, d=1):
        return x.diff(int(d))

    @staticmethod
    def ts_mean(x, d=5):
        d = int(d)
        return x.rolling(d, min_periods=max(1, d // 2)).mean()

    @staticmethod
    def ts_std(x, d=5):
        d = int(d)
        return x.rolling(d, min_periods=max(2, d // 2)).std()

    @staticmethod
    def ts_min(x, d=5):
        d = int(d)
        return x.rolling(d, min_periods=max(1, d // 2)).min()

    @staticmethod
    def ts_max(x, d=5):
        d = int(d)
        return x.rolling(d, min_periods=max(1, d // 2)).max()

    @staticmethod
    def ts_rank(x, d=10):
        """최근 d일 안에서 오늘 값의 백분위 (0 ~ 1)"""
        d = int(d)
        return x.rolling(d, min_periods=max(2, d // 2)).rank(pct=True)

    @staticmethod
    def ts_corr(x, y, d=10):
        d = int(d)
        return x.rolling(d, min_periods=max(3, d // 2)).corr(y).replace([np.inf, -np.inf], np.nan)

    # ------------------------------------------------------------ 횡단면 (같은 날짜)
    @staticmethod
    def cs_rank(x):
        return x.rank(axis=1, pct=True)

    @classmethod
    def cs_zscore(cls, x):
        std = x.std(axis=1)
        return x.sub(x.mean(axis=1), axis=0).div(std.where(std > cls.EPS, np.nan), axis=0)

    @staticmethod
    def cs_demean(x):
        return x.sub(x.mean(axis=1), axis=0)


OPERATOR_REGISTRY = {
    'abs': AlphaOperators.abs, 'log': AlphaOperators.log, 'sign': AlphaOperators.sign,
    'ts_delay': AlphaOperators.ts_delay, 'ts_delta': AlphaOperators.ts_delta,
    'ts_mean': AlphaOperators.ts_mean, 'ts_std': AlphaOperators.ts_std,
    'ts_min': AlphaOperators.ts_min, 'ts_max': AlphaOperators.ts_max,
    'ts_rank': AlphaOperators.ts_rank, 'ts_corr': AlphaOperators.ts_corr,
    'cs_rank': AlphaOperators.cs_rank, 'cs_zscore': AlphaOperators.cs_zscore,
    'cs_demean': AlphaOperators.cs_demean,
}

# 창 길이 인자의 최솟값 (최댓값은 ast_parser.MAX_WINDOW). 마지막 인자가 창 길이
WINDOW_MIN = {'ts_delay': 1, 'ts_delta': 1, 'ts_mean': 1, 'ts_std': 2, 'ts_min': 1, 'ts_max': 1,
              'ts_rank': 2, 'ts_corr': 3}
