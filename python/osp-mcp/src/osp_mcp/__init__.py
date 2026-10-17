"""osp-mcp (layer L6): the MCP server through which AI agents draft surveys. See README.md."""

from .drafting import ALLOWED_COMMANDS, BLOCKED_OPS, Drafting, DraftingError, outline
from .recipes import ChoiceSpec, PageSpec, QuestionSpec, RowSpec

__all__ = [
    "ALLOWED_COMMANDS",
    "BLOCKED_OPS",
    "ChoiceSpec",
    "Drafting",
    "DraftingError",
    "PageSpec",
    "QuestionSpec",
    "RowSpec",
    "outline",
]
