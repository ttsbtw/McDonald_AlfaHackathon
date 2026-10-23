"""Internal decision rules, kept separate from the risk score."""

from .config import RULES_VERSION
from .rules import evaluate_underwriting

__all__ = ["RULES_VERSION", "evaluate_underwriting"]
