"""계산필드용 안전한 수식 평가기.

관리자가 웹 화면에서 입력한 계산식(예: "round(weight / ((height/100) ** 2), 1)")을
파이썬 eval()로 그대로 실행하면 임의 코드 실행 위험이 있으므로, AST를 검사해서
허용된 연산자/함수만 통과시키는 최소 산술 계산기를 사용합니다.
"""

import ast
import operator

_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.FloorDiv: operator.floordiv,
}
_ALLOWED_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_ALLOWED_FUNCS = {
    "round": round,
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
}


class FormulaError(ValueError):
    pass


def _eval_node(node, variables):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, variables)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise FormulaError("숫자 상수만 사용할 수 있습니다.")
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise FormulaError(f"참조한 변수 '{node.id}' 값이 없습니다.")
        val = variables[node.id]
        if val is None or val == "":
            raise FormulaError(f"변수 '{node.id}' 값이 비어 있어 계산할 수 없습니다.")
        try:
            return float(val)
        except (TypeError, ValueError):
            raise FormulaError(f"변수 '{node.id}' 값을 숫자로 변환할 수 없습니다: {val!r}")
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        left = _eval_node(node.left, variables)
        right = _eval_node(node.right, variables)
        return _ALLOWED_BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
        return _ALLOWED_UNARYOPS[type(node.op)](_eval_node(node.operand, variables))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
            raise FormulaError("허용되지 않은 함수 호출입니다.")
        args = [_eval_node(a, variables) for a in node.args]
        return _ALLOWED_FUNCS[node.func.id](*args)
    if isinstance(node, ast.List):
        return [_eval_node(e, variables) for e in node.elts]
    raise FormulaError(f"허용되지 않은 수식 구문입니다: {ast.dump(node)}")


def evaluate_formula(formula: str, variables: dict):
    """formula: 파이썬 산술식 문자열, variables: {변수명: 값} 딕셔너리."""
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"수식 문법 오류: {e}")
    return _eval_node(tree, variables)
