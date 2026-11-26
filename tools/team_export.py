"""팀 공유: 장 마감 뒤 내 장부를 구글 드라이브 공유 폴더로 내보낸다

    python tools/team_export.py          (장 마감 뒤, 15:31 이후)

팀원 저장소에도 이 파일 하나만 tools/ 폴더에 복사해서 쓴다 (이 저장소의 다른 코드에 기대지 않음).
필요한 것: config.STRATEGIES, data/<장부>/trades.csv·state.json, trader/kis_client.py의 KISClient().get_price

.env
    TEAM_DIR    공유 폴더 (예: G:\\내 드라이브\\quant-team, 구글 드라이브 PC 프로그램이 팀원과 맞춰 줌)
    TEAM_NAME   내 이름 = 공유 폴더 안의 내 폴더 이름 (예: 세람)

<TEAM_DIR>/<TEAM_NAME>/ 에 쓰는 것
    books.json                장부 목록 [{book, label, account, capital}] (주간 랭킹은 account가 mock인 장부만)
    <장부>/trades.csv          매매 기록 그대로
    <장부>/equity.csv          장 마감 총자산 하루 한 줄 (day, equity, cash, holdings, positions). 다시 돌리면 그날 줄을 바꿈
    minute/<날짜>/<종목>.csv    그날 매매한 종목(과 v3 후보·업종 동료)의 1분봉 (data/minute에 있을 때만)
    v3/<날짜>.csv, v3_effect.csv  장 마감 반전 v3 판단과 효과 (tools/v3_report.py가 있는 저장소만)
API 키와 .env는 내보내지 않는다. 보유 종목은 한국투자 현재가(장 마감 뒤면 종가)로 평가하고, 조회가 안 되면 매입가로.
"""
import csv
import importlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = ROOT / 'data'
ACCOUNT = {'mock': '모의', 'paper': '가상'}
EQUITY_FIELDS = ['day', 'equity', 'cash', 'holdings', 'positions']


def books(strategies):
    """[{book, label, account, capital}] config.STRATEGIES 두 가지 형식 모두
    ('strategy': '모듈.클래스' 형식은 run.py처럼 장부 이름을 짓고, 아니면 'book'·'name'을 그대로)"""
    out = []
    for s in strategies:
        account = s.get('account', 'paper')
        if 'strategy' in s:
            module, cls = s['strategy'].rsplit('.', 1)
            book = s.get('book') or f'{account}_{module}'
            try:
                k = getattr(importlib.import_module('strategies.' + module), cls)
                name = f'{k.name} {getattr(k, "VERSION", "")}'.strip()
            except Exception:                        # 전략 모듈을 못 읽어도 장부는 내보낸다
                name = cls
        else:
            book, name = s['book'], s.get('name', s['book'])
        out.append({'book': book, 'label': f'{ACCOUNT.get(account, account)}·{name}', 'account': account,
                    'capital': s.get('capital', 0)})
    return out


def equity(state, price):
    """state.json 내용과 price(code) → (총자산, 현금, 보유 평가액, 종목 수)"""
    held = state.get('positions', {})
    value = sum(p['qty'] * price(code, p) for code, p in held.items())
    return state['cash'] + value, state['cash'], value, len(held)


def put_row(path, row):
    """equity.csv에 그날 한 줄 (같은 날 줄이 있으면 바꾼다)"""
    rows = []
    if path.exists():
        with open(path, encoding='utf-8', newline='') as f:
            rows = [r for r in csv.DictReader(f) if r['day'] != row['day']]
    rows = sorted(rows + [row], key=lambda r: r['day'])
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=EQUITY_FIELDS)
        w.writeheader()
        w.writerows(rows)


def run(day=None, log=print):
    team, me = os.getenv('TEAM_DIR', '').strip(), os.getenv('TEAM_NAME', '').strip()
    if not team or not me:
        log('팀 공유 건너뜀 (.env에 TEAM_DIR, TEAM_NAME이 없음)')
        return
    if not Path(team).is_dir():
        log(f'팀 공유 실패 : 공유 폴더가 없습니다 ({team}). 구글 드라이브 프로그램이 켜져 있는지 확인하세요.')
        return
    import config
    today = datetime.now().strftime('%Y%m%d')
    day = day or today
    if day != today:                                 # 장부 상태는 지금 것뿐이라 지난날 총자산은 못 만든다
        log(f'{day}는 오늘이 아니라 매매 기록과 분봉만 내보냅니다 (총자산 줄은 안 씀)')
    elif datetime.now().strftime('%H%M') < '1531':
        log('주의 : 장 마감 전이라 보유 종목은 지금 가격으로 평가합니다 (마감 뒤 다시 돌리면 그날 줄을 바꿈)')
    out = Path(team) / me
    out.mkdir(parents=True, exist_ok=True)
    bs = books(config.STRATEGIES)
    (out / 'books.json').write_text(json.dumps(bs, ensure_ascii=False, indent=2), encoding='utf-8')

    client, prices = None, {}

    def price(code, p):
        nonlocal client
        if code not in prices:
            try:
                if client is None:
                    from trader.kis_client import KISClient
                    client = KISClient()
                prices[code] = client.get_price(code)['price'] or p['avg_price']
            except Exception as ex:
                log(f'{p.get("name", code)}({code}) 가격 조회 실패, 매입가로 평가 ({ex})')
                prices[code] = p['avg_price']
        return prices[code]

    traded = set()
    for b in bs:
        src, dst = DATA / b['book'], out / b['book']
        if not (src / 'state.json').exists():
            continue
        dst.mkdir(exist_ok=True)
        if (src / 'trades.csv').exists():
            shutil.copyfile(src / 'trades.csv', dst / 'trades.csv')
            with open(src / 'trades.csv', encoding='utf-8-sig', newline='') as f:
                stamp = f'{day[:4]}-{day[4:6]}-{day[6:]}'
                traded |= {r[2] for r in csv.reader(f) if r and r[0].startswith(stamp)}   # 3번째 칸 = 종목코드
        if day != today:
            continue
        state = json.loads((src / 'state.json').read_text(encoding='utf-8'))
        eq, cash, value, n = equity(state, price)
        put_row(dst / 'equity.csv', {'day': day, 'equity': round(eq), 'cash': round(cash),
                                     'holdings': round(value), 'positions': n})
    try:                                             # 장 마감 반전 v3 사후 분석이 있는 저장소만 (팀원 저장소는 건너뜀)
        from tools import v3_report
        res = v3_report.analyze(day)
    except Exception:
        res = None
    if res is not None:
        table = res[0]
        dec = DATA / 'paper_close_reversal_v3' / 'decisions' / f'{day}.csv'
        with open(dec, encoding='utf-8', newline='') as f:
            peers = {r['code']: r['peers'] or '' for r in csv.DictReader(f)}           # 같은 종목은 마지막 판단 것
        table = table.assign(peers=table['code'].map(peers).fillna(''))
        (out / 'v3').mkdir(exist_ok=True)
        table.to_csv(out / 'v3' / f'{day}.csv', index=False, encoding='utf-8')
        if (DATA / 'paper_close_reversal_v3' / 'report.csv').exists():
            shutil.copyfile(DATA / 'paper_close_reversal_v3' / 'report.csv', out / 'v3_effect.csv')
        traded |= {c for p in table['peers'] for c in str(p).split()} | set(table['code'])   # 업종 비교 차트용 분봉
    for code in traded:
        src = DATA / 'minute' / day / f'{code}.csv'
        if src.exists():
            (out / 'minute' / day).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, out / 'minute' / day / f'{code}.csv')
    log(f'팀 공유 : 장부 {len(bs)}개, 그날 매매 종목 {len(traded)}개 → {out}')


if __name__ == '__main__':
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / '.env', override=True)
    except ImportError:
        pass
    run(sys.argv[1] if len(sys.argv) > 1 else None)
