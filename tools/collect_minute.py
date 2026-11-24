"""오늘 1분봉 저장 (장 마감 반전 백테스트용 자료 쌓기)

    python tools/collect_minute.py              오늘 거래대금 상위 종목 + KODEX 200·인버스 + 보유 종목
    python tools/collect_minute.py 005930 ...   지정한 종목만
    python tools/collect_minute.py --end 163000 --force
                                                끝 시각을 직접 지정. --force는 이미 받은 파일도 다시 받음

끝 시각은 기본으로 오늘 장 마감 (config.MARKET_HOURS, 수능 날 등은 config.SPECIAL_HOURS).
run.py가 장 마감 1분 뒤에 자동으로 부른다. 직접 실행할 때도 마감 뒤에.
data/minute/YYYYMMDD/<종목코드>.csv 로 저장 (git 제외). 이미 있는 파일은 건너뜀.
한국투자 API는 당일 분봉만 주므로 그날 받지 않으면 다시 구할 수 없다.
"""
import csv
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / '.env', override=True)

from trader.kis_client import KISClient, KISError   # noqa: E402
from trader.symbols import is_etf                    # noqa: E402
from trader.market import hours                      # noqa: E402

ALWAYS = ['069500', '114800']                        # KODEX 200, KODEX 인버스
FIELDS = ['date', 'time', 'open', 'high', 'low', 'close', 'volume', 'value']


def default_codes(client, extra=()):
    codes = list(ALWAYS) + list(extra)
    try:                                             # 업종별 대장주 바구니 (장 마감 반전 v3 사후 분석용)
        from trader import basket
        b = basket.load()
        codes += list(b['code']) if b is not None else []
    except Exception as ex:                          # 바구니 문제로 분봉 저장 전체가 멈추지 않게
        print('대장주 바구니 읽기 실패 :', ex)
    for market in ('0000', '0001', '1001'):          # 전체, 코스피, 코스닥 거래대금 상위 각 30
        try:
            codes += [r['code'] for r in client.get_trade_value_rank(market) if not is_etf(r['name'])]
        except KISError as ex:
            print('거래대금 순위 실패 :', ex)
    return list(dict.fromkeys(codes))


def collect(client, codes, log=print, end=None, force=False):
    day = datetime.now().strftime('%Y%m%d')
    end = end or f'{hours(day)[1]:04d}00'            # 오늘 장 마감 (수능 날 등은 config.SPECIAL_HOURS)
    out = ROOT / 'data' / 'minute' / day
    out.mkdir(parents=True, exist_ok=True)
    done = fail = 0
    for code in codes:
        path = out / f'{code}.csv'
        if path.exists() and not force:
            continue
        try:
            bars = client.get_minute_bars(code, end=end)
        except (KISError, OSError) as ex:
            fail += 1
            log(f'분봉 실패 {code} : {ex}')
            continue
        if not bars:
            continue
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(bars)
        done += 1
    log(f'분봉 저장 {done}종목 (실패 {fail}) → data/minute/{day}/')
    return done


if __name__ == '__main__':
    args = sys.argv[1:]
    end = args[args.index('--end') + 1] if '--end' in args else None
    force = '--force' in args
    skip = {args.index('--end') + 1} if '--end' in args else set()      # --end 뒤의 시각은 종목코드가 아님
    codes = [a for i, a in enumerate(args) if i not in skip and a.isdigit() and len(a) == 6]
    c = KISClient()
    collect(c, codes or default_codes(c), end=end, force=force)
