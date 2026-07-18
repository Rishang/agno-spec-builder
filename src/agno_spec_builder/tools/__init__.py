"""Built-in tool registry. Applications may mutate or replace it before building."""

from agno.tools import Function, Toolkit
from agno.tools.calculator import CalculatorTools
from agno.tools.coding import CodingTools
from agno.tools.python import PythonTools
from agno.tools.user_feedback import UserFeedbackTools

from agno_spec_builder.tools.a2a import A2ATools
from agno_spec_builder.tools.bash import BashTools

TOOL_REGISTRY: dict[str, Function | Toolkit] = {
    "bash": BashTools(),
    "coding": CodingTools(),
    "python": PythonTools(),
    "calculator": CalculatorTools(),
    "ask_user": UserFeedbackTools(),
    "a2a": A2ATools(),
}

__all__ = ["TOOL_REGISTRY", "A2ATools", "BashTools"]
