"""장부: 마이너가 시험한 후보를 하나도 빼지 않고 기록 (data/research/miner/, git 제외)

    ledger.jsonl      15절 IC 1단계로 시험한 72개 (그대로 둠)
    ledger_top.jsonl  18절 상위 200 평균 대비 맨 위 초과 수익 1단계로 시험한 95개 (그대로 둠)
    ledger_kospi.jsonl  코스피 대비 맨 위 초과 수익 1단계로 시험한 것

시험 횟수를 세기 위한 것이기도 하다. 많이 시험할수록 우연히 통과하는 후보가 섞이므로,
나중에 검증 구간으로 넘길 때 "몇 개 중에서 골랐는지"를 같이 본다.
합격(passed)했고 기존 합격 후보와 겹치지 않는 것이 풀(pool)이다.
"""
import ast
import json
from datetime import datetime
from pathlib import Path

MINER_DIR = Path(__file__).resolve().parent.parent.parent / 'data' / 'research' / 'miner'
IC_LEDGER = MINER_DIR / 'ledger.jsonl'
TOP_LEDGER = MINER_DIR / 'ledger_top.jsonl'
LEDGER = MINER_DIR / 'ledger_kospi.jsonl'
PREVIOUS = (IC_LEDGER, TOP_LEDGER)                 # --rescore로 옮겨 올 옛 장부
DIVERSITY_MAX = 0.7


def key(formula):
    """공백·괄호 차이를 무시한 같은 수식 판별용 키 (문법이 틀리면 원문)"""
    try:
        return ast.dump(ast.parse(formula.strip(), mode='eval'))
    except SyntaxError:
        return formula.strip()


class Ledger:
    def __init__(self, path=LEDGER):
        self.path = Path(path)
        self.rows = []
        if self.path.exists():
            with open(self.path, encoding='utf-8') as f:
                self.rows = [json.loads(line) for line in f if line.strip()]
        self.keys = {key(r['formula']) for r in self.rows}

    def seen(self, formula):
        return key(formula) in self.keys

    def add(self, row):
        row = {'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), **row}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
        self.rows.append(row)
        self.keys.add(key(row['formula']))

    def pool(self):
        return [r for r in self.rows if r['status'] == 'accepted']

    def best(self, k=5, statuses=('accepted', 'passed', 'failed', 'duplicate', 'weak_top')):
        """피드백용: 맨 위 초과 수익이 높은 순 (A, B 중 낮은 쪽 기준)"""
        rows = [r for r in self.rows if r['status'] in statuses and r.get('ex_b') is not None]
        return sorted(rows, key=lambda r: -min(r['ex_a'], r['ex_b']))[:k]
