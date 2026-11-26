"""알림: 화면 + 날짜별 로그 파일 + 슬랙

전략마다 채널과 메시지 앞머리를 따로 둔다.
    모의투자 전략 → MOCK_SLACK_CHANNEL (예: #seram-quant), 앞머리 [모의·전략 v1]
    가상 전략     → PAPER_SLACK_CHANNEL (예: #paper-trading), 앞머리 [가상·전략 v1]

.env 값
    SLACK_BOT_TOKEN        슬랙 봇 토큰 (없으면 슬랙 없이 로그만 남김)
    MOCK_SLACK_CHANNEL     모의투자 전략 알림 채널
    PAPER_SLACK_CHANNEL    가상 전략 알림 채널
    LIVE_SLACK_CHANNEL     실시간 잔고판 채널 (없으면 #seram-quant)
"""
import os
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / 'data' / 'logs'
DEFAULT_CHANNELS = {'MOCK_SLACK_CHANNEL': '#seram-quant',
                    'PAPER_SLACK_CHANNEL': '#paper-trading',
                    'LIVE_SLACK_CHANNEL': '#seram-quant'}     # 실시간 잔고판 (trader/live_board.py)


class Notifier:
    def __init__(self, channel_env='PAPER_SLACK_CHANNEL', label=''):
        self.channel = os.getenv(channel_env) or DEFAULT_CHANNELS.get(channel_env, '#paper-trading')
        self.prefix = f'[{label}] ' if label else ''
        self.slack = None
        token = os.getenv('SLACK_BOT_TOKEN')
        self.off_reason = '.env에서 SLACK_BOT_TOKEN을 찾지 못함'
        if token:
            try:
                from slack_sdk import WebClient
                self.slack = WebClient(token=token)
            except ImportError:                     # 가상환경(.venv) 밖의 Python으로 실행한 경우가 대부분
                self.off_reason = 'slack_sdk가 없음, .venv\\Scripts\\activate 뒤에 실행했는지 확인'

    def log(self, message):
        """화면과 로그 파일에만 남긴다."""
        line = datetime.now().strftime('[%m/%d %H:%M:%S] ') + self.prefix + str(message)
        print(line, flush=True)
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOG_DIR / (datetime.now().strftime('%Y%m%d') + '.log'),
                      'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except OSError:
            pass

    def send(self, message):
        """화면, 로그 파일, 슬랙에 모두 남긴다. 슬랙이 실패해도 계속 진행한다."""
        self.log(message)
        if self.slack is None:
            return
        try:
            self.slack.chat_postMessage(
                channel=self.channel,
                text=self.prefix + datetime.now().strftime('[%m/%d %H:%M:%S] ') + message)
        except Exception as ex:
            self.log(f'(슬랙 전송 실패: {ex})')

    def status(self):
        return (f'켜짐 (채널 {self.channel})' if self.slack is not None
                else f'꺼짐 ({self.off_reason})')
