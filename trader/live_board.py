"""실시간 잔고판: 슬랙 메시지 하나를 1분마다 고쳐 쓴다 (메시지를 고치면 슬랙 알림이 가지 않음)

채널: .env의 LIVE_SLACK_CHANNEL, 없으면 #seram-quant
메시지 번호는 data/live_board.json에 적어 두어 run.py를 다시 켜도 같은 날이면 같은 메시지를 고친다.
run.py가 끝날 때(마감 10분 전) 마지막으로 고치고 '마감'을 붙인다. 다음 날은 새 메시지.
잔고판이 실패해도 매매에는 영향 없음 (오류는 화면에만).
"""
import json
import time
from datetime import datetime
from pathlib import Path

STATE = Path(__file__).resolve().parent.parent / 'data' / 'live_board.json'
EVERY = 60                                  # 초
INDEX = ('069500', 'KODEX 200')             # 시장 흐름 표시용 (지수 시세 조회가 따로 없어 ETF로)


def dot(x):
    return '🟢' if x > 0 else '🔴' if x < 0 else '⚪'


class LiveBoard:
    def __init__(self, note):
        """note: trader.notifier.Notifier (슬랙 연결과 채널을 같이 쓴다)"""
        self.note = note
        self.last = 0.0
        self.channel_id = self.ts = None
        self.today = datetime.now().strftime('%Y%m%d')
        try:
            saved = json.loads(STATE.read_text(encoding='utf-8'))
            if saved.get('date') == self.today:
                self.channel_id, self.ts = saved['channel'], saved['ts']
        except (OSError, ValueError, KeyError):
            pass

    def message(self, runners, quotes, now, final=False):
        """(알림 미리보기용 한 줄, 슬랙 Block Kit 블록). 장부마다 칸 하나 (2열, 휴대폰에서는 1열)"""
        codes = {c for r in runners for c in r.broker.positions}
        q = {code: quotes.get(code) for code in [*codes, INDEX[0]]}
        prices = {code: x['price'] for code, x in q.items()}
        fields, total = [], 0
        for r in runners:
            b = r.broker
            eq = b.equity(prices)
            # shortcut: '오늘'은 아침 장부 기준(보유 종목은 매입가)과의 차이, 전날부터 들고 온 종목은 어제 움직임도 섞임
            day = eq - b.state['today'].get('start_equity', eq)
            total += day
            # 장부마다 산 가격이 달라서 수익률은 그 장부의 매입가 대비. 손실 큰 순서, 한 줄에 두 종목
            xs = sorted((prices[c] / p['avg_price'] - 1, p.get('name', c)) for c, p in b.positions.items())
            items = [f'{name} {x:+.1%}' for x, name in xs]
            held = '\n'.join(' · '.join(items[i:i + 2]) for i in range(0, len(items), 2)) or '_보유 없음_'
            fields.append({'type': 'mrkdwn',
                           'text': f'*{r.note.prefix.strip()[1:-1]}*\n{eq:,.0f}원  {dot(day)} {day:+,.0f}\n{held}'})
        status = f'{now:%H:%M} {"마감" if final else "갱신"}'
        blocks = [{'type': 'header', 'text': {'type': 'plain_text', 'text': '📊 실시간 잔고'}},
                  {'type': 'context', 'elements': [{'type': 'mrkdwn', 'text':
                      f'*{status}* · {INDEX[1]} 어제 대비 {q[INDEX[0]]["rate"]:+.2f}% · '
                      f'오늘 합계 {dot(total)} *{total:+,.0f}원*'}]},
                  {'type': 'divider'}]
        blocks += [{'type': 'section', 'fields': fields[i:i + 10]} for i in range(0, len(fields), 10)]  # 칸은 10개까지
        return f'실시간 잔고 {status} · 오늘 합계 {total:+,.0f}원', blocks

    def run(self, runners, quotes, final=False):
        slack = self.note.slack
        if slack is None or (not final and time.time() - self.last < EVERY):
            return
        self.last = time.time()
        try:
            text, blocks = self.message(runners, quotes, datetime.now(), final)
            if self.ts:
                try:
                    slack.chat_update(channel=self.channel_id, ts=self.ts, text=text, blocks=blocks)
                    return
                except Exception as ex:
                    if 'message_not_found' not in str(ex):
                        raise
                    # 누가 메시지를 지웠으면 아래에서 새로 올린다
            r = slack.chat_postMessage(channel=self.note.channel, text=text, blocks=blocks)
            self.channel_id, self.ts = r['channel'], r['ts']
            STATE.write_text(json.dumps({'date': self.today, 'channel': self.channel_id, 'ts': self.ts}),
                             encoding='utf-8')
        except Exception as ex:                 # 매매 흐름 안이라 어떤 오류도 밖으로 내보내지 않는다
            print('실시간 잔고판 실패 :', ex)
