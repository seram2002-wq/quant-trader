"""알파 마이너 v0 1단계: 수식 파서 안전성, 미래 참조 없음, 지표 계산

    python -m unittest discover tests
"""
import unittest

import numpy as np
import pandas as pd

from alpha_miner.engine.ast_parser import AlphaASTParser, AlphaSyntaxError
from alpha_miner.evaluation.metrics import ic_series, top_excess, turnover


def toy(days=60, n=30, seed=0):
    rng = np.random.default_rng(seed)
    idx, cols = pd.bdate_range('2015-01-01', periods=days), [f'{i:06d}' for i in range(n)]
    f = lambda a: pd.DataFrame(a, index=idx, columns=cols)
    close = f(np.cumprod(1 + rng.normal(0, 0.02, (days, n)), axis=0) * 10000)
    return {'close': close, 'open': close * 0.99, 'volume': f(rng.uniform(1e5, 1e6, (days, n))),
            'returns': close.pct_change()}


class Safety(unittest.TestCase):
    def test_rejects_dangerous_or_invalid(self):
        p = AlphaASTParser(toy())
        bad = ["__import__('os').system('dir')", 'close.__class__', 'lambda x: x', 'close ** 2',
               'open(1)', 'ts_mean(close, volume)', 'ts_mean(close, 0)', 'ts_mean(close, 999)',
               'ts_mean(close, True)', 'ts_corr(close, volume, 2)', '1 + 2', 'ts_mean(x=close, d=5)',
               'price', '[close]', 'close if 1 else volume', 'cs_rank()', 'cs_rank(5)',
               'close + ' * 100 + 'close', ' + '.join(['ts_mean(close, 5)'] * 12)]
        for expr in bad:
            with self.assertRaises(AlphaSyntaxError, msg=expr):
                p.evaluate(expr)

    def test_error_message_is_useful_feedback(self):
        with self.assertRaisesRegex(AlphaSyntaxError, "없는 연산자: 'ts_skew'"):
            AlphaASTParser(toy()).evaluate('ts_skew(close, 10)')


class Values(unittest.TestCase):
    def test_matches_pandas_and_guards(self):
        feats = toy()
        p = AlphaASTParser(feats)
        pd.testing.assert_frame_equal(p.evaluate('ts_mean(close, 5)'),
                                      feats['close'].rolling(5, min_periods=2).mean())
        zero = dict(feats, volume=feats['volume'] * 0)
        out = AlphaASTParser(zero).evaluate('close / volume')
        self.assertTrue(out.isna().all().all())                   # 0으로 나누면 inf가 아니라 NaN
        self.assertTrue(AlphaASTParser(feats).evaluate('log(-close)').isna().all().all())

    def test_no_look_ahead(self):
        """40일째 뒤 자료를 바꿔도 40일째까지의 알파 값은 그대로여야 한다"""
        a, b = toy(seed=1), toy(seed=1)
        for k in b:
            b[k].iloc[41:] = b[k].iloc[41:] * 3 + 7
        formulas = ['-ts_delta(close, 5)', 'ts_corr(close, volume, 10)', 'cs_rank(ts_rank(returns, 20))',
                    'cs_zscore(close / ts_mean(volume, 5)) - cs_demean(ts_std(returns, 10))',
                    'ts_max(open, 7) / ts_min(open, 7) * sign(ts_delay(returns, 3))']
        for expr in formulas:
            pd.testing.assert_frame_equal(AlphaASTParser(a).evaluate(expr).iloc[:41],
                                          AlphaASTParser(b).evaluate(expr).iloc[:41], obj=expr)


class Metrics(unittest.TestCase):
    def test_ic_and_turnover(self):
        f = toy()['close']
        mask = f.notna()
        self.assertAlmostEqual(ic_series(f, f * 2, mask).mean(), 1.0)
        self.assertAlmostEqual(ic_series(f, -f, mask).mean(), -1.0)
        static = f.iloc[[0] * len(f)].set_axis(f.index)             # 매일 같은 점수 → 회전율 0
        self.assertEqual(turnover(static, mask, n=5), 0.0)
        flip = pd.DataFrame(np.tile([[1.0] * 15 + [0.0] * 15, [0.0] * 15 + [1.0] * 15], (30, 1)),
                            index=f.index, columns=f.columns)        # 매일 상위가 통째로 바뀜
        self.assertEqual(turnover(flip, mask, n=15), 1.0)

    def test_top_excess_looks_only_at_the_top(self):
        f = toy()['close']
        mask = f.notna()
        fwd = f.pct_change(fill_method=None).shift(-1)
        best = top_excess(fwd, fwd, mask, n=5, every=1, min_names=20, cost=0.0).dropna()
        self.assertTrue((best > 0).all())                              # 미래를 아는 점수 → 맨 위가 늘 평균보다 높음
        # IC는 플러스지만 맨 위 5종목에 가장 나쁜 종목을 올린 점수 → 맨 위 초과 수익은 마이너스
        rk = fwd.rank(axis=1)
        trap = rk.where(rk > 5, 100 - rk)
        self.assertGreater(ic_series(trap, fwd, mask).mean(), 0.1)
        self.assertTrue((top_excess(trap, fwd, mask, n=5, every=1, min_names=20, cost=0.0).dropna() < 0).all())
        static = f.iloc[[0] * len(f)].set_axis(f.index)                # 종목이 안 바뀌면 첫 교체만 비용
        gross = top_excess(static, fwd, mask, n=5, every=10, min_names=20, cost=0.0)
        net = top_excess(static, fwd, mask, n=5, every=10, min_names=20, cost=0.01)
        self.assertAlmostEqual((gross - net).iloc[0], 0.01)
        self.assertTrue(np.allclose((gross - net).iloc[1:], 0.0))
        bench = pd.Series(0.05, index=f.index)                          # 기준을 주면 평가 종목 평균 대신 그것을 뺌
        vs_bench = top_excess(static, fwd, mask, n=5, every=10, min_names=20, cost=0.0, bench=bench)
        top5 = fwd.where(static.rank(axis=1, ascending=False) <= 5).mean(axis=1)
        self.assertTrue(np.allclose(vs_bench, (top5 - 0.05).reindex(vs_bench.index), equal_nan=True))


# ---------------------------------------------------------------- 3단계: GPT 루프 (가짜 GPT·가짜 평가기)
import tempfile                                                      # noqa: E402
from pathlib import Path                                             # noqa: E402
from unittest import mock                                            # noqa: E402

from alpha_miner.generator import llm_miner, prompts                 # noqa: E402
from alpha_miner.mine import Miner                                   # noqa: E402
from alpha_miner.storage.alpha_pool import Ledger                    # noqa: E402


class FakeEvaluator:
    """수식 문자열로 결과를 정한다: bad → error, weak → weak_top, 나머지 → passed"""
    def evaluate(self, f):
        if 'bad' in f:
            return {'status': 'error', 'reason': "없는 피처: 'bad'"}
        ex = -0.001 if 'weak' in f else 0.002
        return {'status': 'weak_top' if ex <= 0 else 'passed', 'sign': 1.0, 'ex_a': ex, 'ex_b': ex,
                'ic_a': 0.03, 'ic_b': 0.03, 'turnover': 0.1, 'reason': 'r'}

    def score(self, f, sign=1.0):
        return f

    def correlation(self, a, b):
        return 0.9 if a.replace(' ', '') [:8] == b.replace(' ', '')[:8] else 0.1


class Loop(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger(Path(tempfile.mkdtemp()) / 'ledger.jsonl')
        self.calls = []

    def fake_propose(self, system, user):
        self.calls.append(user)
        if len(self.calls) == 1:
            return [{'formula': 'cs_rank(close)', 'idea': 'a'}, {'formula': 'bad + close', 'idea': 'b'},
                    {'formula': 'weak(close)', 'idea': 'c'}]
        return [{'formula': 'cs_rank( close )', 'idea': 'same'},           # 공백만 다른 같은 수식
                {'formula': 'cs_rank(volume)', 'idea': 'd'},               # 풀의 첫 수식과 앞 8글자 같음 → 중복
                {'formula': 'ts_mean(volume, 5)', 'idea': 'e'}]

    def test_loop_feedback_dedupe_and_pool(self):
        total = Miner(FakeEvaluator(), self.fake_propose, self.ledger, log=lambda *_: None).run(
            2, 3, prompts.SYSTEM, prompts.user_message)
        self.assertEqual(total, 5)                                        # 같은 수식은 두 번 세지 않음
        self.assertEqual([r['status'] for r in self.ledger.rows],
                         ['accepted', 'error', 'weak_top', 'duplicate', 'accepted'])
        self.assertIn("bad + close  -> error: 없는 피처: 'bad'", self.calls[1])   # 오류가 다음 라운드 피드백으로
        self.assertIn('Best so far', self.calls[1])
        again = Ledger(self.ledger.path)                                  # 파일에서 다시 읽어도 같음
        self.assertEqual(len(again.rows), 5)
        self.assertTrue(again.seen('cs_rank(close)'))

    def test_budget_stops(self):
        total = Miner(FakeEvaluator(), self.fake_propose, self.ledger, log=lambda *_: None).run(
            5, 3, prompts.SYSTEM, prompts.user_message, max_total=2)
        self.assertEqual((total, len(self.ledger.rows)), (2, 2))


class GPTCall(unittest.TestCase):
    def resp(self, code, body):
        return mock.Mock(status_code=code, text=str(body), json=lambda: body)

    def test_parses_and_retries(self):
        ok = self.resp(200, {'choices': [{'message': {'content': '{"formulas": [{"formula": "cs_rank(close)", "idea": "x"}]}'}}]})
        with mock.patch.dict('os.environ', {'OPENAI_API_KEY': 'k'}), mock.patch.object(llm_miner.time, 'sleep'), \
                mock.patch.object(llm_miner.requests, 'post', side_effect=[self.resp(429, 'slow'), ok]) as post:
            out = llm_miner.propose('s', 'u')
        self.assertEqual(out, [{'formula': 'cs_rank(close)', 'idea': 'x'}])
        sent = post.call_args.kwargs
        self.assertEqual(sent['headers']['Authorization'], 'Bearer k')
        self.assertTrue(sent['json']['response_format']['json_schema']['strict'])

    def test_errors(self):
        with mock.patch.dict('os.environ', {'OPENAI_API_KEY': ''}):
            with self.assertRaisesRegex(llm_miner.LLMError, 'OPENAI_API_KEY'):
                llm_miner.propose('s', 'u')
        with mock.patch.dict('os.environ', {'OPENAI_API_KEY': 'k'}), \
                mock.patch.object(llm_miner.requests, 'post', return_value=self.resp(401, 'bad key')) as post:
            with self.assertRaisesRegex(llm_miner.LLMError, 'HTTP 401'):
                llm_miner.propose('s', 'u')
        self.assertEqual(post.call_count, 1)                              # 401은 다시 시도하지 않음



class Coverage(unittest.TestCase):
    def test_starts_when_enough_names_have_scores(self):
        from alpha_miner.evaluation.fitness import coverage_start
        f = toy(days=40, n=30)['close']
        late = f.copy()
        late.iloc[:15] = np.nan                                       # 거래소 자료처럼 늦게 시작
        mask = f.notna()
        a, b = f.index[0], f.index[-1]
        self.assertEqual(coverage_start(f, mask, a, b, min_names=20), f.index[0])
        self.assertEqual(coverage_start(late, mask, a, b, min_names=20), f.index[15])
        self.assertIsNone(coverage_start(late, mask, a, b, min_names=31))



class Focus(unittest.TestCase):
    def test_focus_brief_goes_first(self):
        msg = prompts.user_message(4, [], [], focus='pv')
        self.assertTrue(msg.startswith('Focus: the price-volume correlation family'))
        self.assertNotIn('Focus:', prompts.user_message(4, [], []))


if __name__ == '__main__':
    unittest.main()
