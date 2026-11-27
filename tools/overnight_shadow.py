"""밤사이 보유 그림자 기록: 전날 밤 S&P500이 1% 넘게 빠진 날 10:30에 팔았다면 (docs 23절 후보 규칙) — 2026-11-27

    python -m tools.overnight_shadow            오늘

run.py가 장 마감 뒤 분봉 저장 다음에 부른다. 매매에는 쓰지 않는다.
매일 한 줄: 그날 아침 실제 매도(가상 장부 paper_overnight_etf)와 10:30 매도를 비교. 규칙에 해당하는 날(spy ≤ -1%)만
나중에 모아서 보면 되고, 해당 없는 날도 비교용으로 남긴다.
    spy_pct   : 전날 밤 SPY 등락률 (한국투자 해외 시세, 장 마감 뒤 부르면 미국 전날 장 기준)
    price_1030: 그날 KODEX 200 1분봉 10:30 봉 종가 (data/minute/<날짜>/069500.csv)
    diff_won  : (10:30 가격 - 실제 매도가) × 수량. 비용·슬리피지는 같다고 보고 뺌
결과: data/paper_overnight_etf/exit_shadow.csv (다시 돌리면 그날 줄을 바꿈)
"""
import csv
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from trader.paper_broker import TRADE_FIELDS         # noqa: E402

BOOK = ROOT / 'data' / 'paper_overnight_etf'
OUT = BOOK / 'exit_shadow.csv'
FIELDS = ['day', 'spy_pct', 'rule', 'sell_time', 'sell_price', 'qty', 'price_1030', 'diff_pct', 'diff_won']
RULE = -1.0                                           # 전날 밤 S&P500 -1% 이하


def price_at(day, hhmm):
    """그날 KODEX 200 1분봉에서 hhmm 봉까지의 마지막 종가 (거래 없는 장 시작 전 줄은 뺌)"""
    path = ROOT / 'data' / 'minute' / day / '069500.csv'
    if not path.exists():
        return None
    with open(path, encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(f) if float(r['volume']) > 0 and r['time'].zfill(6)[:4] <= hhmm]
    return float(rows[-1]['close']) if rows else None


def row_for(day, spy_pct, sell, price_1030):
    """sell: 그날 아침 매도 행 (TRADE_FIELDS dict). 계산만"""
    qty, price = int(sell['qty']), float(sell['price'])
    out = {'day': day, 'spy_pct': round(spy_pct, 2), 'rule': int(spy_pct <= RULE), 'sell_time': sell['time'][11:19],
           'sell_price': price, 'qty': qty, 'price_1030': price_1030, 'diff_pct': '', 'diff_won': ''}
    if price_1030:
        out['diff_pct'] = round((price_1030 / price - 1) * 100, 3)
        out['diff_won'] = round((price_1030 - price) * qty)
    return out


def run(client, day=None, log=print):
    day = day or datetime.now().strftime('%Y%m%d')
    stamp = f'{day[:4]}-{day[4:6]}-{day[6:]}'
    trades = BOOK / 'trades.csv'
    if not trades.exists():
        return None
    with open(trades, encoding='utf-8-sig', newline='') as f:
        sells = [r for r in csv.DictReader(f, fieldnames=TRADE_FIELDS) if r['side'] == 'SELL' and r['time'].startswith(stamp)]
    if not sells:
        log(f'밤사이 그림자 : {day} 아침 매도 없음')
        return None
    # shortcut: 미국 휴장 다음 날은 그 전 미국 장 등락이 다시 들어감 (날짜를 안 봄), 규칙 해당일을 모아 볼 때 미국 휴장일만 빼면 됨
    spy = client.get_us_change('SPY', 'AMS') * 100
    row = row_for(day, spy, sells[0], price_at(day, '1030'))
    rows = []
    if OUT.exists():
        with open(OUT, encoding='utf-8', newline='') as f:
            rows = [r for r in csv.DictReader(f) if r['day'] != day]
    with open(OUT, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(sorted(rows + [row], key=lambda r: r['day']))
    log(f'밤사이 그림자 {day}: 전날 밤 SPY {row["spy_pct"]:+.2f}%' + (' (규칙 해당)' if row['rule'] else '')
        + f', 실제 {row["sell_time"]} {row["sell_price"]:,.0f}원 vs 10:30 '
        + (f'{row["price_1030"]:,.0f}원 → {row["diff_won"]:+,}원' if row['price_1030'] else '분봉 없음'))
    return row


if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=True)
    from trader.kis_client import KISClient
    run(KISClient(), sys.argv[1] if len(sys.argv) > 1 else None)
