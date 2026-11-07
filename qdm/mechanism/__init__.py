"""Question-selection and prompt-building logic for problem-driven modeling."""

from .policy import (
    QUESTION_FIELD_SPECS,
    QUESTION_STATUS_WEIGHT,
    build_question_policy,
    pick_next_field,
    rank_question_fields,
    recompute_question_gate,
)
from .prompt import build_question_prompt, build_stop_signal, compact_feature_table

