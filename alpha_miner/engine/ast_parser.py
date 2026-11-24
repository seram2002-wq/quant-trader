"""알파 수식 문자열을 안전하게 실행한다 (eval 쓰지 않음)

ast로 구문 트리를 만든 뒤 화이트리스트에 있는 것만 실행한다: 숫자 상수, 피처 이름, + - * /, 단항 -/+,
OPERATOR_REGISTRY의 함수 호출(키워드 인자 없이). 그 밖은 모두 AlphaSyntaxError.
에러 메시지는 그대로 LLM 다음 라운드 피드백으로 넘길 수 있게 짧고 구체적으로 쓴다.
"""
import ast

import numpy as np
import pandas as pd

from alpha_miner.engine.operators import OPERATOR_REGISTRY, WINDOW_MIN, AlphaOperators

MAX_LENGTH = 400        # 글자 수
MAX_NODES = 60          # 구문 트리 노드 수 (너무 복잡한 수식, 지나친 중첩 막기)
MAX_WINDOW = 250        # 창 길이 최댓값 (약 1년)


class AlphaSyntaxError(Exception):
    """허용되지 않은 문법, 없는 연산자·피처, 잘못된 창 길이"""


class AlphaASTParser:
    def __init__(self, features):
        """features: {피처 이름: 날짜 x 종목 DataFrame}"""
        self.features = features
        self._bin_ops = {ast.Add: AlphaOperators.add, ast.Sub: AlphaOperators.sub,
                         ast.Mult: AlphaOperators.mul, ast.Div: AlphaOperators.div}
        self._unary_ops = {ast.UAdd: lambda x: x, ast.USub: lambda x: -x}

    def check(self, expression):
        """실행하지 않고 문법만 확인. 통과하면 구문 트리를 돌려준다"""
        if len(expression) > MAX_LENGTH:
            raise AlphaSyntaxError(f'수식이 너무 깁니다 ({len(expression)}자, 최대 {MAX_LENGTH}자)')
        try:
            tree = ast.parse(expression.strip(), mode='eval')
        except SyntaxError as e:
            raise AlphaSyntaxError(f'문법 오류: {e.msg}') from e
        n = sum(1 for _ in ast.walk(tree))
        if n > MAX_NODES:
            raise AlphaSyntaxError(f'수식이 너무 복잡합니다 (노드 {n}개, 최대 {MAX_NODES}개)')
        return tree

    def evaluate(self, expression):
        """수식 → 날짜 x 종목 DataFrame (inf는 NaN으로)"""
        result = self._eval_node(self.check(expression).body)
        if not isinstance(result, pd.DataFrame):
            raise AlphaSyntaxError('수식 결과는 피처를 포함해야 합니다 (상수만으로 된 수식 불가)')
        return result.replace([np.inf, -np.inf], np.nan)

    def _eval_node(self, node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return node.value
            raise AlphaSyntaxError(f'허용되지 않은 상수: {node.value!r}')

        if isinstance(node, ast.Name):
            if node.id in self.features:
                return self.features[node.id]
            raise AlphaSyntaxError(f"없는 피처: '{node.id}' (사용 가능: {', '.join(self.features)})")

        if isinstance(node, ast.UnaryOp):
            op = self._unary_ops.get(type(node.op))
            if op is None:
                raise AlphaSyntaxError(f'허용되지 않은 단항 연산자: {type(node.op).__name__}')
            return op(self._eval_node(node.operand))

        if isinstance(node, ast.BinOp):
            op = self._bin_ops.get(type(node.op))
            if op is None:
                raise AlphaSyntaxError(f'허용되지 않은 연산자: {type(node.op).__name__} (+ - * / 만 가능)')
            return op(self._eval_node(node.left), self._eval_node(node.right))

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise AlphaSyntaxError('메서드 호출(obj.func)은 허용되지 않습니다')
            name = node.func.id
            if name not in OPERATOR_REGISTRY:
                raise AlphaSyntaxError(f"없는 연산자: '{name}' (사용 가능: {', '.join(OPERATOR_REGISTRY)})")
            if node.keywords:
                raise AlphaSyntaxError(f'{name}: 키워드 인자는 쓸 수 없습니다')
            args = list(node.args)
            if name in WINDOW_MIN:                       # 마지막 인자 = 창 길이, 정수 상수만
                if not args:
                    raise AlphaSyntaxError(f'{name}: 인자가 없습니다')
                w = args[-1]
                if not (isinstance(w, ast.Constant) and isinstance(w.value, int) and not isinstance(w.value, bool)):
                    raise AlphaSyntaxError(f'{name}: 마지막 인자(창 길이)는 정수 상수여야 합니다')
                if not WINDOW_MIN[name] <= w.value <= MAX_WINDOW:
                    raise AlphaSyntaxError(f'{name}: 창 길이 {w.value}는 {WINDOW_MIN[name]} ~ {MAX_WINDOW} 사이여야 합니다')
            values = [self._eval_node(a) for a in args]
            if not values or not isinstance(values[0], pd.DataFrame):
                raise AlphaSyntaxError(f'{name}: 첫 인자는 피처(또는 피처로 만든 값)여야 합니다')
            try:
                return OPERATOR_REGISTRY[name](*values)
            except TypeError as e:
                raise AlphaSyntaxError(f'{name}: 인자 개수가 맞지 않습니다') from e

        raise AlphaSyntaxError(f'지원하지 않는 문법: {type(node).__name__}')
