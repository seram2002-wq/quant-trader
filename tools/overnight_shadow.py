"""밤사이 보유 그림자 기록: 아침에 시초가보다 +0.5% / +1% 오르면 팔고, 안 오르면 10:59에 팔았다면 — 2026-11-27

    python -m tools.overnight_shadow            오늘

docs 23절 후보 규칙(전날 밤 SOXX가 빠진 날 시초가 +1% 반등 매도가 나았음)을 실전 자료로 다시 확인하려고 쌓는다.
run.py가 장 마감 뒤 분봉 저장 다음에 부른다. 매매에는 쓰지 않는다.
매일 한 줄: 그날 아침 실제 매도(가상 장부 paper_overnight_etf)와 두 규칙을 비교. SOXX가 빠지지 않은 날도 비교용으로 남긴다.
    soxx_pct, spy_pct : 전날 밤 등락률 (한국투자 해외 시세, 장 마감 뒤 부르면 미국 전날 장 기준)
    a05, a10          : 그날 KODEX 200 1분봉 종가가 시초가 × (1 + 0.5% / 1%) 이상이 된 첫 봉의 종가와 시각, 10:59까지 없으면 10:59 종가
    diff_*_won        : (규칙 매도가 - 실제 매도가) × 수량. 비용·슬리피지는 같다고 보고 뺌
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
RULES = {'a05': 0.005, 'a10': 0.01}                  # 시초가 대비 오르면 파는 폭
DEADLINE = '1059'
FIELDS = ['day', 'soxx_pct', 'spy_pct', 'soxx_down', 'sell_time', 'sell_price', 'qty', 'open',
          'a05_time', 'a05_price', 'diff_a05_won', 'a10_time', 'a10_price', 'diff_a10_won']


def morning_bars(day):
    """그날 KODEX 200 1분봉 [(hhmm, 시가, 종가)] 09:00 ~ 10:59 (거래 없는 장 시작 전 줄은 뺌)"""
    path = ROOT / 'data' / 'minute' / day / '069500.csv'
    if not path.exists():
        return []
    with open(path, encoding='utf-8') as f:
        return [(r['time'].zfill(6)[:4], float(r['open']), float(r['close'])) for r in csv.DictReader(f)
                if float(r['volume']) > 0 and r['time'].zfill(6)[:4] <= DEADLINE]


def rebound_sell(bars, up):
    """시초가 × (1 + up) 이상인 첫 봉 종가에 매도, 없으면 마지막(10:59) 봉 종가. (시각, 가격) 또는 None"""
    if not bars:
        return None
    target = bars[0][1] * (1 + up)
    for hm, _, close in bars:
        if close >= target:
            return hm, close
    return bars[-1][0], bars[-1][2]


def row_for(day, soxx_pct, spy_pct, sell, bars):
    """sell: 그날 아침 매도 행 (TRADE_FIELDS dict). 계산만"""
    qty, price = int(sell['qty']), float(sell['price'])
    out = {'day': day, 'soxx_pct': round(soxx_pct, 2), 'spy_pct': round(spy_pct, 2), 'soxx_down': int(soxx_pct < 0),
           'sell_time': sell['time'][11:19], 'sell_price': price, 'qty': qty, 'open': bars[0][1] if bars else ''}
    for key, up in RULES.items():
        hit = rebound_sell(bars, up)
        out[f'{key}_time'], out[f'{key}_price'] = hit if hit else ('', '')
        out[f'diff_{key}_won'] = round((hit[1] - price) * qty) if hit else ''
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
    # shortcut: 미국 휴장 다음 날은 그 전 미국 장 등락이 다시 들어감 (날짜를 안 봄), 모아 볼 때 미국 휴장일만 빼면 됨
    soxx = client.get_us_change('SOXX', 'NAS') * 100
    spy = client.get_us_change('SPY', 'AMS') * 100
    row = row_for(day, soxx, spy, sells[0], morning_bars(day))
    rows = []
    if OUT.exists():
        with open(OUT, encoding='utf-8', newline='') as f:
            rows = [r for r in csv.DictReader(f) if r['day'] != day and set(r) >= set(FIELDS)]   # 예전 형식 줄은 버림
    with open(OUT, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        w.writeheader()
        w.writerows(sorted(rows + [row], key=lambda r: r['day']))
    msg = ', '.join(f'+{RULES[k]:.1%} {row[k + "_time"]} {row[k + "_price"]:,.0f}원 ({row["diff_" + k + "_won"]:+,}원)'
                    for k in RULES if row[k + '_time'])
    log(f'밤사이 그림자 {day}: 전날 밤 SOXX {row["soxx_pct"]:+.2f}%, SPY {row["spy_pct"]:+.2f}% | '
        f'실제 {row["sell_time"]} {row["sell_price"]:,.0f}원 vs ' + (msg or '분봉 없음'))
    return row


if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=True)
    from trader.kis_client import KISClient
    run(KISClient(), sys.argv[1] if len(sys.argv) > 1 else None)
