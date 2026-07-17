"""CEL expression wrapper — compile once at build time, eval at runtime.

Usage:
    expr = CELUtil("plan.effort == 'high'")
    if expr.check(ns):   # ns = {step_name: json_serialisable_value}
        ...
    val = expr.eval(ns)  # raw CEL result
"""

import logging

import celpy

log = logging.getLogger(__name__)


class CELUtil:
    """Wraps a single CEL expression: compile once, eval many times.

    Raises ValueError at construction if the expression is syntactically invalid,
    so mistyped `when`/`case` expressions fail at build time, not mid-run.
    """

    def __init__(self, expr: str) -> None:
        self.expr = expr
        try:
            env = celpy.Environment()
            self._prog = env.program(env.compile(expr))
        except Exception as e:
            raise ValueError(f"Invalid CEL expression {expr!r}: {e}") from e

    def eval(self, ns: dict):
        """Evaluate against a namespace of {name: json-serialisable value}."""
        # json_to_cel takes a Python object (not a JSON string); ns values are
        # already plain Python (Pydantic models are pre-converted via model_dump).
        activation = {k: celpy.json_to_cel(v) for k, v in ns.items()}
        try:
            return self._prog.evaluate(activation)
        except celpy.CELEvalError as e:
            log.warning(f"CEL eval error ({self.expr!r}): {e}")
            return None

    def check(self, ns: dict) -> bool:
        """Evaluate and coerce to bool — for `when:` conditional guards."""
        return bool(self.eval(ns))
