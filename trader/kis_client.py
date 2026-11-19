"""한국투자증권 Open API 클라이언트 (모의투자 서버)

시세 조회는 모든 전략이 쓰고, 주문·잔고 기능은 모의투자 계좌에 연결한 전략만 쓴다.

.env 값
    KIS_APP_KEY, KIS_APP_SECRET   모의투자 앱키, 시크릿
    KIS_ACCOUNT_NO                모의투자 계좌번호 (12345678-01). 주문하는 전략이 있을 때만 필요
    KIS_TOKEN_FILE                접근 토큰 저장 파일 (보통은 비워 둠, 기본 data/.kis_token_mock.json)
                                  다른 앱키로 받은 토큰 파일이면 쓰지 않고 새로 발급받는다.

연결 처리
    조회(GET)는 연결이 끊기면 새 연결로 다시 시도한다 (같은 조회를 다시 해도 안전).
    주문(POST)은 자동으로 다시 보내지 않는다. 응답 없이 끊겨도 주문이 이미 들어갔을 수
    있어서, 다시 보내면 두 번 사게 될 수 있다. 이 경우 OrderUncertain을 일으키고,
    호출한 쪽이 잔고로 체결 여부를 확인한다.
"""
import os
import re
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

BASE_URL = 'https://openapivts.koreainvestment.com:29443'   # 모의투자 서버
TR_PREFIX = 'V'                                             # 모의투자 거래 코드 첫 글자
INTERVAL = 1.0                                              # 호출 사이 최소 간격(초)
RATE_LIMIT_CODES = ('EGW00201', 'EGW00215')                 # 호출 제한: 잠시 뒤 재시도


class KISError(Exception):
    """API가 실패 응답을 돌려줬을 때"""


class OrderUncertain(KISError):
    """주문을 보냈지만 응답을 받지 못함 (주문이 들어갔는지 모름)"""


class KISClient:
    def __init__(self):
        self.app_key = self._env('KIS_APP_KEY')
        self.app_secret = self._env('KIS_APP_SECRET')
        default = Path(__file__).resolve().parent.parent / 'data' / '.kis_token_mock.json'
        self.token_file = Path(os.getenv('KIS_TOKEN_FILE') or default)
        self.session = requests.Session()
        self._token = None
        self._token_expires = 0.0
        self._last_call = 0.0
        self._account = None

    @staticmethod
    def _env(name):
        value = (os.getenv(name) or '').strip().strip('"').strip("'")
        if not value:
            raise KISError(f'.env 파일에 {name} 값이 없습니다.')
        return value

    @property
    def account(self):
        """(계좌번호 앞 8자리, 뒤 2자리). 주문하는 전략이 처음 쓸 때 읽는다."""
        if self._account is None:
            m = re.fullmatch(r'(\d{8})-?(\d{2})', self._env('KIS_ACCOUNT_NO'))
            if not m:
                raise KISError('KIS_ACCOUNT_NO는 12345678-01처럼 숫자 8자리-2자리여야 합니다.')
            self._account = (m.group(1), m.group(2))
        return self._account

    # ------------------------------------------------------------ 토큰
    def _get_token(self):
        """접근 토큰. 만료 10분 전까지는 저장된 토큰을 다시 쓴다."""
        if self._token and self._token_expires > time.time() + 600:
            return self._token
        if self.token_file.exists():
            try:
                saved = json.loads(self.token_file.read_text(encoding='utf-8'))
                # 이 앱키로 받은 토큰만 다시 쓴다 (표시가 없는 예전 형식이나 다른 앱키의 토큰은 버림)
                if (saved.get('expires_at', 0) > time.time() + 600
                        and saved.get('app_key_tail') == self.app_key[-6:]):
                    self._token = saved['access_token']
                    self._token_expires = saved['expires_at']
                    return self._token
            except (ValueError, KeyError, OSError):
                pass
        res = self._request('post', BASE_URL + '/oauth2/tokenP', retry=True,
                            json={'grant_type': 'client_credentials',
                                  'appkey': self.app_key, 'appsecret': self.app_secret})
        data = self._json(res)
        if 'access_token' not in data:
            raise KISError('토큰 발급 실패: '
                           f"{data.get('error_code', res.status_code)} "
                           f"{data.get('error_description', '')}")
        self._token = data['access_token']
        self._token_expires = time.time() + int(data.get('expires_in', 86400))
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(json.dumps({
            'access_token': self._token, 'expires_at': self._token_expires,
            'app_key_tail': self.app_key[-6:],      # 앱키가 바뀌면 토큰을 새로 받기 위한 표시
        }), encoding='utf-8')
        return self._token

    # ------------------------------------------------------------ 공통 호출
    @staticmethod
    def _json(res):
        try:
            return res.json()
        except ValueError:
            raise KISError(f'응답을 해석할 수 없습니다 (HTTP {res.status_code})')

    def _request(self, method, url, retry, **kwargs):
        """HTTP 요청. retry=True면 연결이 끊겼을 때 새 연결로 두 번까지 다시 시도한다."""
        for attempt in range(3 if retry else 1):
            gap = INTERVAL - (time.time() - self._last_call)
            if gap > 0:
                time.sleep(gap)
            try:
                return getattr(self.session, method)(url, timeout=10, **kwargs)
            except requests.exceptions.ConnectionError:
                self.session.close()
                self.session = requests.Session()          # 끊긴 연결은 버리고 새로 연다
                if not retry:
                    raise OrderUncertain('주문 응답을 받지 못했습니다 (연결 끊김)')
                if attempt == 2:
                    raise
                time.sleep(1)
            except requests.exceptions.Timeout:
                if not retry:
                    raise OrderUncertain('주문 응답을 받지 못했습니다 (시간 초과)')
                if attempt == 2:
                    raise
            finally:
                self._last_call = time.time()

    def _headers(self, tr_id):
        return {
            'content-type': 'application/json; charset=utf-8',
            'authorization': 'Bearer ' + self._get_token(),
            'appkey': self.app_key, 'appsecret': self.app_secret,
            'tr_id': tr_id, 'custtype': 'P',
        }

    def _call(self, method, path, tr_id, retry=True, **kwargs):
        for attempt in range(4):
            res = self._request(method, BASE_URL + path, retry,
                                headers=self._headers(tr_id), **kwargs)
            data = self._json(res)
            if data.get('rt_cd') == '0':
                return data
            if data.get('msg_cd') in RATE_LIMIT_CODES and attempt < 3:
                time.sleep(1.5 * (attempt + 1))   # 호출 제한은 서버가 처리하지 않은 것이라 다시 보내도 안전
                continue
            raise KISError(f"{data.get('msg_cd', res.status_code)} "
                           f"{data.get('msg1', '').strip()}")

    def _get(self, path, tr_id, params):
        return self._call('get', path, tr_id, params=params)

    @staticmethod
    def _num(d, key):
        try:
            return float(d.get(key) or 0)
        except (TypeError, ValueError):
            return 0.0

    # ------------------------------------------------------------ 시세
    def get_price(self, code):
        """현재가 정보. vwap은 오늘 누적 거래대금 ÷ 누적 거래량 (거래량 가중 평균가)"""
        out = self._get('/uapi/domestic-stock/v1/quotations/inquire-price',
                        'FHKST01010100',
                        {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': code})['output']
        volume = self._num(out, 'acml_vol')
        value = self._num(out, 'acml_tr_pbmn')
        return {
            'code': code,
            'price': int(self._num(out, 'stck_prpr')),
            'open': int(self._num(out, 'stck_oprc')),
            'high': int(self._num(out, 'stck_hgpr')),
            'low': int(self._num(out, 'stck_lwpr')),
            'rate': self._num(out, 'prdy_ctrt'),
            'volume': int(volume),
            'value': int(value),
            'vwap': value / volume if volume else 0.0,
            'status': out.get('iscd_stat_cls_code') or '',   # 51 관리, 52 투자위험, 53 투자경고, 58 거래정지 등
            'warn': out.get('mrkt_warn_cls_code') or '',     # 00 없음, 01 투자주의, 02 투자경고, 03 투자위험
        }

    def get_trade_value_rank(self, market='0000'):
        """거래대금 상위 종목 (최대 30개): [{'code', 'name', 'price', 'value'}]

        market: '0000' 전체, '0001' 코스피, '1001' 코스닥
        """
        data = self._get('/uapi/domestic-stock/v1/quotations/volume-rank',
                         'FHPST01710000',
                         {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_COND_SCR_DIV_CODE': '20171',
                          'FID_INPUT_ISCD': market, 'FID_DIV_CLS_CODE': '1',
                          'FID_BLNG_CLS_CODE': '3',              # 3: 거래금액순
                          'FID_TRGT_CLS_CODE': '111111111',
                          'FID_TRGT_EXLS_CLS_CODE': '0000000000',
                          'FID_INPUT_PRICE_1': '0', 'FID_INPUT_PRICE_2': '0',
                          'FID_VOL_CNT': '0', 'FID_INPUT_DATE_1': ''})
        rows = []
        for r in data.get('output', []) or []:
            code = r.get('mksc_shrn_iscd')
            if code:
                rows.append({'code': code, 'name': (r.get('hts_kor_isnm') or code).strip(),
                             'price': int(self._num(r, 'stck_prpr')),
                             'value': int(self._num(r, 'acml_tr_pbmn'))})
        return rows

    def get_ohlc(self, code):
        """최근 약 30거래일 일별 시세 (최신 날짜가 맨 앞, 수정주가)

        장중에 부르면 맨 앞 줄이 오늘이고, close에는 지금 가격이 들어 있다.
        volume: 거래량, foreign: 외국인 순매수 수량
        """
        data = self._get('/uapi/domestic-stock/v1/quotations/inquire-daily-price',
                         'FHKST01010400',
                         {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': code,
                          'FID_PERIOD_DIV_CODE': 'D', 'FID_ORG_ADJ_PRC': '0'})
        rows = []
        for r in data.get('output', []):
            if r.get('stck_bsop_date'):
                rows.append({'date': r['stck_bsop_date'],
                             'open': int(r['stck_oprc']), 'high': int(r['stck_hgpr']),
                             'low': int(r['stck_lwpr']), 'close': int(r['stck_clpr']),
                             'volume': int(self._num(r, 'acml_vol')),
                             'foreign': int(self._num(r, 'frgn_ntby_qty'))})
        rows.sort(key=lambda x: x['date'], reverse=True)
        return rows

    def get_minute_bars(self, code, end='153000'):
        """오늘 1분봉 전체 (09:00 ~ end, 시간순). 한 번에 30개씩 거꾸로 받아 이어 붙인다.

        [{'time': 'HHMMSS', 'open', 'high', 'low', 'close', 'volume', 'value'(누적 거래대금)}]
        """
        bars, until = {}, end
        for _ in range(20):
            data = self._get('/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice',
                             'FHKST03010200',
                             {'FID_ETC_CLS_CODE': '', 'FID_COND_MRKT_DIV_CODE': 'J',
                              'FID_INPUT_ISCD': code, 'FID_INPUT_HOUR_1': until,
                              'FID_PW_DATA_INCU_YN': 'Y'})
            rows = [r for r in data.get('output2', []) or [] if r.get('stck_cntg_hour')]
            if not rows:
                break
            for r in rows:
                bars[r['stck_cntg_hour']] = {
                    'date': r.get('stck_bsop_date', ''), 'time': r['stck_cntg_hour'],
                    'open': int(self._num(r, 'stck_oprc')), 'high': int(self._num(r, 'stck_hgpr')),
                    'low': int(self._num(r, 'stck_lwpr')), 'close': int(self._num(r, 'stck_prpr')),
                    'volume': int(self._num(r, 'cntg_vol')), 'value': int(self._num(r, 'acml_tr_pbmn'))}
            first = min(r['stck_cntg_hour'] for r in rows)
            if first <= '090000':
                break
            t = datetime.strptime(first, '%H%M%S') - timedelta(minutes=1)
            until = t.strftime('%H%M%S')
        return [bars[k] for k in sorted(bars)]

    # ------------------------------------------------------------ 계좌 (주문하는 전략만)
    def get_balance(self):
        """보유 종목 {code: {'name', 'qty', 'sellable', 'avg_price'}}"""
        cano, prdt = self.account
        data = self._get('/uapi/domestic-stock/v1/trading/inquire-balance',
                         TR_PREFIX + 'TTC8434R',
                         {'CANO': cano, 'ACNT_PRDT_CD': prdt, 'AFHR_FLPR_YN': 'N',
                          'OFL_YN': '', 'INQR_DVSN': '02', 'UNPR_DVSN': '01',
                          'FUND_STTL_ICLD_YN': 'N', 'FNCG_AMT_AUTO_RDPT_YN': 'N',
                          'PRCS_DVSN': '01', 'CTX_AREA_FK100': '', 'CTX_AREA_NK100': ''})
        held = {}
        for r in data.get('output1', []):
            qty = int(self._num(r, 'hldg_qty'))
            if qty > 0:
                held[r.get('pdno')] = {'name': r.get('prdt_name'), 'qty': qty,
                                       'sellable': int(self._num(r, 'ord_psbl_qty')),
                                       'avg_price': self._num(r, 'pchs_avg_pric')}
        return held

    def get_buyable_cash(self, code='005930'):
        """지금 주문에 쓸 수 있는 현금 (미수 없이 살 수 있는 금액)"""
        cano, prdt = self.account
        out = self._get('/uapi/domestic-stock/v1/trading/inquire-psbl-order',
                        TR_PREFIX + 'TTC8908R',
                        {'CANO': cano, 'ACNT_PRDT_CD': prdt, 'PDNO': code,
                         'ORD_UNPR': '', 'ORD_DVSN': '01',
                         'CMA_EVLU_AMT_ICLD_YN': 'N', 'OVRS_ICLD_YN': 'N'}).get('output') or {}
        for key in ('nrcvb_buy_amt', 'ord_psbl_cash'):
            if out.get(key) not in (None, ''):
                return int(self._num(out, key))
        raise KISError('주문 가능 금액을 응답에서 찾지 못했습니다.')

    def order(self, side, code, qty, best=False):
        """현금 주문. best=True면 최유리지정가(03), 아니면 시장가(01). 주문 정보를 돌려준다.

        연결이 끊기면 다시 보내지 않고 OrderUncertain을 일으킨다.
        """
        cano, prdt = self.account
        body = {'CANO': cano, 'ACNT_PRDT_CD': prdt, 'PDNO': code,
                'ORD_DVSN': '03' if best else '01', 'ORD_QTY': str(int(qty)),
                'ORD_UNPR': '0', 'EXCG_ID_DVSN_CD': 'KRX'}
        if side == 'sell':
            body['SLL_TYPE'] = '01'
        tr_id = TR_PREFIX + ('TTC0012U' if side == 'buy' else 'TTC0011U')
        data = self._call('post', '/uapi/domestic-stock/v1/trading/order-cash', tr_id,
                          retry=False, data=json.dumps(body))
        out = data.get('output') or {}
        return {'order_no': out.get('ODNO'), 'org_no': out.get('KRX_FWDG_ORD_ORGNO')}

    def cancel(self, order):
        """주문의 미체결 잔량 전부 취소"""
        cano, prdt = self.account
        body = {'CANO': cano, 'ACNT_PRDT_CD': prdt,
                'KRX_FWDG_ORD_ORGNO': order.get('org_no') or '',
                'ORGN_ODNO': order['order_no'], 'ORD_DVSN': '00',
                'RVSE_CNCL_DVSN_CD': '02', 'ORD_QTY': '0', 'ORD_UNPR': '0',
                'QTY_ALL_ORD_YN': 'Y', 'EXCG_ID_DVSN_CD': 'KRX'}
        self._call('post', '/uapi/domestic-stock/v1/trading/order-rvsecncl',
                   TR_PREFIX + 'TTC0013U', retry=False, data=json.dumps(body))

    def get_fill(self, order_no, code):
        """오늘 주문의 체결 결과 (수량, 평균 체결가). 조회가 안 되면 None"""
        cano, prdt = self.account
        today = datetime.now().strftime('%Y%m%d')
        try:
            data = self._get('/uapi/domestic-stock/v1/trading/inquire-daily-ccld',
                             TR_PREFIX + 'TTC8001R',
                             {'CANO': cano, 'ACNT_PRDT_CD': prdt,
                              'INQR_STRT_DT': today, 'INQR_END_DT': today,
                              'SLL_BUY_DVSN_CD': '00', 'INQR_DVSN': '00', 'PDNO': code,
                              'CCLD_DVSN': '00', 'ORD_GNO_BRNO': '', 'ODNO': order_no,
                              'INQR_DVSN_3': '00', 'INQR_DVSN_1': '',
                              'CTX_AREA_FK100': '', 'CTX_AREA_NK100': ''})
        except KISError:
            return None
        for r in data.get('output1', []) or []:
            if (r.get('odno') or '').lstrip('0') == (order_no or '').lstrip('0'):
                qty = int(self._num(r, 'tot_ccld_qty'))
                amt = self._num(r, 'tot_ccld_amt')
                return {'qty': qty, 'avg_price': amt / qty if qty else 0.0}
        return None
