"""오늘 1분봉 저장 (장 마감 반전 백테스트용 자료 쌓기)

    python tools/collect_minute.py              오늘 거래대금 상위 종목 + KODEX 200·인버스 + 보유 종목
    python tools/collect_minute.py 005930 ...   지정한 종목만

run.py가 장 마감 뒤(15:31 이후)에 자동으로 부른다. 직접 실행할 때도 15:31 이후에.
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

ALWAYS = ['069500', '114800']                        # KODEX 200, KODEX 인버스
FIELDS = ['date', 'time', 'open', 'high', 'low', 'close', 'volume', 'value']


def default_codes(client, extra=()):
    codes = list(ALWAYS) + list(extra)
    for market in ('0000', '0001', '1001'):          # 전체, 코스피, 코스닥 거래대금 상위 각 30
        try:
            codes += [r['code'] for r in client.get_trade_value_rank(market) if not is_etf(r['name'])]
        except KISError as ex:
            print('거래대금 순위 실패 :', ex)
    return list(dict.fromkeys(codes))


def collect(client, codes, log=print):
    day = datetime.now().strftime('%Y%m%d')
    out = ROOT / 'data' / 'minute' / day
    out.mkdir(parents=True, exist_ok=True)
    done = fail = 0
    for code in codes:
        path = out / f'{code}.csv'
        if path.exists():
            continue
        try:
            bars = client.get_minute_bars(code)
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
    c = KISClient()
    codes = sys.argv[1:] or default_codes(c)
    collect(c, codes)
