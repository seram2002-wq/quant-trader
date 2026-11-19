# research — 전략 백테스트 도구

새 전략을 가상 장부에 올리기 전에 과거 데이터로 시험하는 도구입니다. 모두 같은 데이터,
같은 비용, 같은 채택 기준으로 시험해야 결과를 서로 비교할 수 있습니다.
지금까지의 시험 결과는 [docs/backtest_summary.md](../docs/backtest_summary.md)에 있습니다.

## 1. 데이터 받기 (처음 한 번, 이후 가끔)

```
pip install -r requirements.txt
python tools\fetch_research_data.py     # 필수: 전 종목 일별 시세 2010년~, 업종, KODEX 200 일봉
python tools\fetch_dart.py              # 선택: DART 재무 (.env에 DART_API_KEY)
```

거래소 수급·배당(PER, PBR, 배당수익률, 외국인·기관 순매수)을 쓰려면 data.krx.co.kr에
**아이디·비밀번호 방식으로** 가입하고 `.env`에 `KRX_ID`, `KRX_PW`를 넣은 뒤
`python tools\krx_login_check.py`로 확인하고 `fetch_research_data.py`를 다시 실행합니다.

| 데이터 | 위치 | 기간 | 비고 |
|---|---|---|---|
| 전 종목 일별 시세 | `data/marcap/` | 1995년~ (기본 2010년~) | 상장폐지 종목 포함, 1 ~ 2거래일 늦음 |
| 업종 | `data/research/sector.csv` | 지금 상장 종목만 | 상장폐지 종목은 업종 모름 |
| DART 재무 | `data/research/dart/` | 2015년 사업연도~ | 공시 다음 거래일부터 사용 |
| 거래소 PER·PBR·배당, 수급 | `data/research/fundamental/`, `flow/` | 2013년~ 월별 | 발표 다음 거래일부터 사용 |
| KODEX 200·인버스 | `data/research/intraday/` | 일봉 2007년~, 1시간봉 2년, 5분봉 60일 | 야후 파이낸스 |

메모리: 2010년부터 불러오면 2 ~ 3GB 정도 씁니다. 부족하면 `load_panel('2014-01-01')`처럼 줄입니다.

## 2. 새 전략 시험하기

`research/examples/factor_template.py`를 복사해서 `make_score()`만 바꿉니다.

```python
from research.data import load_panel
from research.evaluate import judge
from research import factors as f

p = load_panel('2010-06-01')        # p.add_dart(), p.add_krx()로 재무·수급 추가
score = f.combine(f.momentum(p, 12, 1), f.low_volatility(p, 250))   # 날짜 × 종목, 클수록 좋음
judge(p, score, name='내 전략', neutral=True)
```

```
python -m research.examples.factor_template
```

`judge()`는 탐색·검증 구간 × 6개 설정(종목 범위 150·200·300, 종목 수 20·30)을 돌려
표와 통과 여부를 보여 줍니다. 한 설정만 보고 고르지 않으려고 중앙값으로 판정합니다.

### 점수표 규칙 (미래 정보 방지)

- 그날까지의 값으로만 만든다. `shift(-n)`처럼 미래 값을 당겨 쓰지 않는다
- `backtest()`가 점수를 2거래일 늦춰 쓴다 (`lag=2`, 데이터가 늦게 오는 실제 상황과 같게).
  이미 늦춘 점수를 넘길 때만 `lag=0`
- 매매는 그날 종가 (실시간 전략의 15:05 매매와 비슷)

### `research/factors.py`에 있는 재료

| 함수 | 뜻 | 필요한 것 |
|---|---|---|
| `momentum(p, 12, 1)` | 12개월 수익률 (최근 1개월 제외) | |
| `reversal(p, 21)` | 최근 21일 수익률의 반대 | |
| `low_volatility(p, 250)` | 1년 변동성이 낮을수록 | |
| `high52(p)` | 52주 최고가에 가까울수록 | |
| `small(p)`, `low_turnover(p)` | 작을수록, 거래가 적을수록 | |
| `book_to_price`, `earnings_yield`, `roe`, `operating_profitability`, `low_leverage` | 재무 | `p.add_dart()` |
| `institution_selling(p, 3)`, `foreign_selling`, `dividend_yield` | 수급·배당 | `p.add_krx()` |
| `combine(a, b, ..., weights=)` | 여러 점수를 날짜별 순위로 바꿔 가중 평균 | |

### `backtest()` 주요 옵션

| 옵션 | 기본 | 뜻 |
|---|---|---|
| `n` | 20 | 보유 종목 수 (같은 금액) |
| `hold` | 2n | 보유 종목은 이 순위 안이면 계속 보유 (매매 줄이기) |
| `size` | 200 | 종목 범위: 시가총액 상위 보통주 (거래대금 10억 이상) |
| `every` | 21 | 며칠마다 교체 (21 월, 5 주, 1 매일) |
| `neutral` | False | True면 업종 안 순위로 고름 |
| `sector_cap` | None | 같은 업종 최대 종목 수 |
| `lag` | 2 | 점수를 늦춰 쓰는 거래일 |

비용은 `config.py`의 `FEE_RATE`(0.015%), `SLIPPAGE`(0.05%), `STOCK_SELL_TAX`(0.20%)를 씁니다.

## 3. 채택 기준 (2026-11-19)

| 구간 | 기간 | 기준 |
|---|---|---|
| 탐색 | 2012 ~ 2019 | 연 수익률 ≥ 코스피, 최대 낙폭이 코스피보다 작게 |
| 검증 | 2020 ~ 2024 | 연 수익률 ≥ 코스피 + 5%p, 최대 낙폭이 코스피보다 작게 |
| 시험 | 2025 ~ | 규칙을 고르는 동안 보지 않음. 최종 후보만 `judge(..., final=True)`로 한 번 |

- 코스피는 직접 계산한 시가총액 가중 지수. "상위 200 동일 비중"도 참고로 같이 나옵니다
- 통과하면 가상 장부(`config.py`의 `'account': 'paper'`)에서 몇 주 실제로 확인한 뒤 판단합니다
- 결과를 보고 규칙을 여러 번 고치면 과거에 맞춘 전략이 됩니다. 시험한 횟수도 같이 기록해 두세요

## 4. 예시

| 파일 | 내용 |
|---|---|
| `examples/factor_template.py` | 새 전략 틀 (업종 중립 모멘텀 + 저변동성) |
| `examples/lgbm_walkforward.py` | LightGBM 굴려 가며 학습 (`pip install lightgbm`) |
| `examples/overnight_etf.py` | 밤사이 보유 (KODEX 200, 왕복 비용별) |

## 5. 한계

- 업종은 지금 상장 종목 기준이라 과거에 업종이 바뀐 종목은 반영 못 함
- 현금 배당은 종목 수익률에 빠짐 (배당락 날 수익률이 낮게 잡혀 조금 보수적)
- 공매도, 장중 가격(분봉)은 없음. 장 마감 반전은 `data/minute/`에 분봉이 쌓인 뒤 따로 시험
