"""장 시간. 수능 날처럼 개장·마감 시각이 다른 날은 config.SPECIAL_HOURS에 적는다.

전략과 설정의 시각은 HHMM이 아니라 그날 장 시간 기준 분으로 적는다.
    0 이상 : 개장 N분 뒤    (5   → 평소 09:05, 수능 날 10:05)
    음수   : 마감 N분 전    (-15 → 평소 15:15, 수능 날 16:15)
"""
from datetime import datetime

import config


def hours(day=None):
    """(개장 HHMM, 마감 HHMM). day: 'YYYYMMDD', 없으면 오늘"""
    day = day or datetime.now().strftime('%Y%m%d')
    return config.SPECIAL_HOURS.get(day, config.MARKET_HOURS)


def shift(hhmm, minutes):
    """HHMM에 분을 더한 HHMM"""
    m = hhmm // 100 * 60 + hhmm % 100 + minutes
    return m // 60 * 100 + m % 60


def at(offset, day=None):
    """장 시간 기준 분 → 그날의 HHMM"""
    open_, close = hours(day)
    return shift(open_, offset) if offset >= 0 else shift(close, offset)
