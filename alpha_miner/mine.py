"""알파 마이너 v0: GPT가 수식을 제안 → 탐색 구간 안에서 평가 → 결과를 피드백해 다시 제안

    python -m alpha_miner.mine --rounds 5 --n 8          (라운드마다 8개, 모두 40개까지)
    python -m alpha_miner.mine --report                  지금까지 장부 요약만
    python -m alpha_miner.mine --rescore                 옛 장부(15·18절)의 수식을 GPT 없이 지금 1단계로 다시 평가

마이너는 2019-12-31까지만 불러온다. 풀에 들어간 후보는 검증 구간(2020 ~ 2024) 시험 전 후보일 뿐이며,
검증은 따로 한 번만 한다 (시험한 총 개수와 함께 기록). 장부: storage/alpha_pool.py
"""
import argparse

from alpha_miner.storage.alpha_pool import DIVERSITY_MAX, PREVIOUS, Ledger

START, END = '2010-06-01', '2019-12-31'


class Miner:
    def __init__(self, evaluator, propose, ledger, log=print):
        """propose(system, user) -> [{'formula', 'idea'}]. 시험할 때 가짜로 바꿔 끼운다"""
        self.ev, self.propose, self.ledger, self.log = evaluator, propose, ledger, log
        self.pool_scores = {}

    def _pool_score(self, row):
        if row['formula'] not in self.pool_scores:
            self.pool_scores[row['formula']] = self.ev.score(row['formula'], row['sign'])
        return self.pool_scores[row['formula']]

    def judge(self, formula, idea, round_no):
        if self.ledger.seen(formula):
            return None                                       # 이미 시험한 수식은 다시 세지 않음
        r = self.ev.evaluate(formula)
        if r['status'] == 'passed':
            score = self.ev.score(formula, r['sign'])
            for row in self.ledger.pool():
                c = self.ev.correlation(score, self._pool_score(row))
                if abs(c) >= DIVERSITY_MAX:
                    r = {**r, 'status': 'duplicate', 'reason': f"풀의 {row['formula']}와 상관 {c:+.2f}"}
                    break
            else:
                r = {**r, 'status': 'accepted'}
        row = {'round': round_no, 'formula': formula, 'idea': idea, **r}
        self.ledger.add(row)
        self.log(f"[{round_no}] {r['status']:9} {formula}  {r.get('reason', '')}")
        return row

    def run(self, rounds, n, system, user_message, max_total=None):
        recent, total = [], 0
        for k in range(1, rounds + 1):
            proposals = self.propose(system, user_message(n, self.ledger.best(), recent))
            recent = []
            for p in proposals[:n]:
                if max_total is not None and total >= max_total:
                    return total
                row = self.judge(p['formula'], p.get('idea', ''), k)
                if row:
                    recent.append(row)
                    total += 1
        return total


def report(ledger):
    from collections import Counter
    c = Counter(r['status'] for r in ledger.rows)
    print(f'시험한 수식 {len(ledger.rows)}개: ' + ', '.join(f'{s} {c[s]}' for s in
                                                       ('accepted', 'duplicate', 'failed', 'passed', 'weak_top', 'error') if c[s]))
    for r in ledger.pool():
        print(f"  풀: {r['formula']}  초과 {r['ex_a']:+.2%}/{r['ex_b']:+.2%}  {r['reason']}")
    for r in ledger.best():
        print(f"  상위: {r['formula']}  초과 {r['ex_a']:+.2%}/{r['ex_b']:+.2%}  "
              f"IC {r['ic_a']:+.3f}/{r['ic_b']:+.3f}  {r['status']}")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--rounds', type=int, default=5)
    ap.add_argument('--n', type=int, default=8)
    ap.add_argument('--max', type=int, default=None, help='이번 실행에서 시험할 최대 개수')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--rescore', action='store_true', help='옛 장부의 수식을 지금 1단계로 다시 평가 (GPT 안 씀)')
    ap.add_argument('--model', default=None, help='OpenAI 모델 (없으면 .env OPENAI_MODEL)')
    ap.add_argument('--focus', default=None, help='집중할 계열 (generator/prompts.py FOCUS 키, 예: pv)')
    a = ap.parse_args()
    ledger = Ledger()
    if not a.report:
        from dotenv import load_dotenv
        from alpha_miner.data.loader import load
        from alpha_miner.evaluation.fitness import Evaluator
        from alpha_miner.generator import llm_miner, prompts
        from research.data import ROOT
        load_dotenv(ROOT / '.env', override=True)
        p, feats = load(START, END)
        propose = lambda system, user: llm_miner.propose(system, user, model=a.model)   # noqa: E731
        message = lambda n, best, recent: prompts.user_message(n, best, recent, a.focus)   # noqa: E731
        miner = Miner(Evaluator(p, feats), propose, ledger)
        if a.rescore:
            for r in (r for path in PREVIOUS for r in Ledger(path).rows):
                miner.judge(r['formula'], r.get('idea', ''), 0)          # 라운드 0 = 옛 장부에서 옮긴 것 (같은 수식은 한 번만)
        else:
            miner.run(a.rounds, a.n, prompts.SYSTEM, message, a.max)
    report(ledger)
