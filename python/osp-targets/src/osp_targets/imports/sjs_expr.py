"""SurveyJS expression text → osp-expr JSON (the subset our model can express).

From the public SurveyJS expression documentation: ``{name}`` variables, ``=`` / ``==`` /
``equal``, ``<>`` / ``!=`` / ``notequal``, ``< <= > >=`` (``less``, ``greater`` ...),
``empty`` / ``notempty``, ``contains`` / ``notcontains``, ``anyof`` / ``allof``, ``and``
/ ``&&``, ``or`` / ``||``, ``!`` / ``not``, arithmetic ``+ - * /``, ``iif(c, a, b)``,
quoted strings, numbers, ``true`` / ``false`` and ``[a, b]`` arrays. Anything else (other
functions, ``%``, ``^``, array indexes) makes the whole expression unconvertible: the
caller reports it as a loss. Clean-room: no SurveyJS code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

SJS_PIPE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.\-]*)\}")

_TOKEN = re.compile(
    r"""\s*(?:
    (?P<var>\{[^{}]*\})|
    (?P<num>-?\d+(?:\.\d+)?)|
    (?P<str>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")|
    (?P<op><>|<=|>=|==|!=|=|<|>|&&|\|\||[()+\-*/,\[\]!])|
    (?P<word>[A-Za-z_][A-Za-z0-9_]*)
    )""",
    re.VERBOSE,
)

_COMPARE_WORDS = {
    "=": "==",
    "==": "==",
    "equal": "==",
    "equals": "==",
    "<>": "!=",
    "!=": "!=",
    "notequal": "!=",
    "notequals": "!=",
    "<": "<",
    "less": "<",
    "<=": "<=",
    "lessorequal": "<=",
    ">": ">",
    "greater": ">",
    ">=": ">=",
    "greaterorequal": ">=",
}
_SET_WORDS = {"contains", "notcontains", "anyof", "allof", "empty", "notempty"}


class _Unsupported(Exception):
    pass


@dataclass
class ExprResult:
    expr: dict[str, Any] | None
    reason: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class _Tok:
    kind: str
    text: str


def _tokens(src: str) -> list[_Tok]:
    out: list[_Tok] = []
    pos = 0
    while pos < len(src):
        if src[pos:].strip() == "":
            break
        m = _TOKEN.match(src, pos)
        if not m or m.end() == pos:
            raise _Unsupported(f"unexpected character {src[pos : pos + 1]!r}")
        pos = m.end()
        kind = m.lastgroup or ""
        out.append(_Tok(kind, m.group(kind)))
    return out


class _Parser:
    """Recursive descent over the token list; builds osp-expr JSON directly."""

    def __init__(
        self,
        tokens: list[_Tok],
        names: dict[str, str],
        types: dict[str, str],
        values: dict[str, dict[str, int | str]],
    ) -> None:
        self.t = tokens
        self.i = 0
        self.names, self.types, self.values = names, types, values
        self.notes: list[str] = []

    # -- helpers -------------------------------------------------------------------------

    def peek(self) -> _Tok | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self) -> _Tok:
        tok = self.peek()
        if tok is None:
            raise _Unsupported("unexpected end of expression")
        self.i += 1
        return tok

    def at_word(self, *words: str) -> bool:
        tok = self.peek()
        return tok is not None and tok.kind in ("word", "op") and tok.text.lower() in words

    # -- grammar -------------------------------------------------------------------------

    def parse(self) -> dict[str, Any]:
        e = self.or_()
        if self.peek() is not None:
            raise _Unsupported(f"unexpected {self.peek().text!r}")  # type: ignore[union-attr]
        return e

    def or_(self) -> dict[str, Any]:
        args = [self.and_()]
        while self.at_word("or", "||"):
            self.take()
            args.append(self.and_())
        return args[0] if len(args) == 1 else {"kind": "or", "args": args}

    def and_(self) -> dict[str, Any]:
        args = [self.not_()]
        while self.at_word("and", "&&"):
            self.take()
            args.append(self.not_())
        return args[0] if len(args) == 1 else {"kind": "and", "args": args}

    def not_(self) -> dict[str, Any]:
        if self.at_word("!", "not", "negate"):
            self.take()
            inner = self.not_()
            return inner["arg"] if inner.get("kind") == "not" else {"kind": "not", "arg": inner}
        return self.comparison()

    def comparison(self) -> dict[str, Any]:
        left = self.additive()
        tok = self.peek()
        if tok is None:
            return left
        word = tok.text.lower()
        if word in _COMPARE_WORDS:
            self.take()
            right = self.additive()
            return self._compare(_COMPARE_WORDS[word], left, right)
        if word in _SET_WORDS:
            self.take()
            if word == "empty":
                return {"kind": "not", "arg": self._answered(left)}
            if word == "notempty":
                return self._answered(left)
            right = self.additive()
            return self._set_op(word, left, right)
        return left

    def additive(self) -> dict[str, Any]:
        e = self.multiplicative()
        while self.at_word("+", "-"):
            op = self.take().text
            e = {"kind": "arith", "op": op, "left": e, "right": self.multiplicative()}
        return e

    def multiplicative(self) -> dict[str, Any]:
        e = self.unary()
        while self.at_word("*", "/"):
            op = self.take().text
            e = {"kind": "arith", "op": op, "left": e, "right": self.unary()}
        return e

    def unary(self) -> dict[str, Any]:
        if self.at_word("-"):
            self.take()
            inner = self.unary()
            if inner["kind"] == "int":
                return {"kind": "int", "value": -inner["value"]}
            if inner["kind"] == "decimal":
                return {"kind": "decimal", "value": str(-Decimal(inner["value"]))}
            return {"kind": "arith", "op": "-", "left": {"kind": "int", "value": 0}, "right": inner}
        return self.primary()

    def primary(self) -> dict[str, Any]:
        tok = self.take()
        if tok.kind == "var":
            return self._ref(tok.text[1:-1].strip())
        if tok.kind == "num":
            return _number(tok.text)
        if tok.kind == "str":
            return {"kind": "text", "value": _unquote(tok.text)}
        if tok.kind == "op" and tok.text == "(":
            e = self.or_()
            if not self.at_word(")"):
                raise _Unsupported("missing ')'")
            self.take()
            return e
        if tok.kind == "op" and tok.text == "[":
            items: list[dict[str, Any]] = []
            while not self.at_word("]"):
                items.append(self.or_())
                if self.at_word(","):
                    self.take()
            self.take()
            return {"kind": "__array", "items": items}
        if tok.kind == "word":
            w = tok.text.lower()
            if w == "true":
                return {"kind": "bool", "value": True}
            if w == "false":
                return {"kind": "bool", "value": False}
            if w in ("null", "undefined"):
                return {"kind": "null"}
            if self.at_word("("):
                return self._call(w)
            raise _Unsupported(f"unknown word {tok.text!r}")
        raise _Unsupported(f"unexpected {tok.text!r}")

    def _call(self, name: str) -> dict[str, Any]:
        self.take()  # (
        args: list[dict[str, Any]] = []
        while not self.at_word(")"):
            args.append(self.or_())
            if self.at_word(","):
                self.take()
            elif not self.at_word(")"):
                raise _Unsupported("bad argument list")
        self.take()
        if name == "iif" and len(args) == 3:
            return {"kind": "if", "cond": args[0], "then": args[1], "else": args[2]}
        raise _Unsupported(f"function {name}() is not supported")

    # -- semantics -----------------------------------------------------------------------

    def _ref(self, name: str) -> dict[str, Any]:
        ours = self.names.get(name)
        if ours is None and "." in name:  # {grid.row}
            ours = self.names.get(name)
        if ours is None:
            raise _Unsupported(f"{{{name}}} names no imported question")
        return {"kind": "ref", "id": ours}

    def _ref_id(self, e: dict[str, Any]) -> str | None:
        return e["id"] if e.get("kind") == "ref" else None

    def _answered(self, e: dict[str, Any]) -> dict[str, Any]:
        if e.get("kind") != "ref":
            raise _Unsupported("empty / notempty needs a question")
        return {"kind": "answered", "ref": e}

    def _literal_for(self, rid: str, lit: dict[str, Any]) -> dict[str, Any]:
        """A literal compared with a choice question, as that question's value type."""
        mapping = self.values.get(rid)
        if mapping is None or lit["kind"] not in ("text", "int", "decimal", "bool"):
            return lit
        key = str(lit["value"]).lower() if lit["kind"] == "bool" else str(lit["value"])
        if key in mapping:
            v = mapping[key]
            return (
                {"kind": "int", "value": v} if isinstance(v, int) else {"kind": "text", "value": v}
            )
        if lit["kind"] == "bool":
            return {"kind": "text", "value": key}
        return lit

    def _compare(self, op: str, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        for e in (left, right):
            if e.get("kind") == "__array":
                raise _Unsupported("arrays can only be used with anyof / allof")
        lid, rid = self._ref_id(left), self._ref_id(right)
        if lid is not None and self.types.get(lid) == "multi" and op in ("==", "!="):
            # {multi} = ['a'] or {multi} = 'a': "exactly these" is not expressible; contains is.
            inner = self._set_op("contains", left, right)
            return inner if op == "==" else {"kind": "not", "arg": inner}
        if lid is not None:
            right = self._literal_for(lid, right)
        elif rid is not None:
            left = self._literal_for(rid, left)
        if op in ("==", "!=") and (right.get("kind") == "bool" or left.get("kind") == "bool"):
            # {q} = true on a non-boolean question: SurveyJS treats it as truthiness.
            ref = left if lid is not None else right
            lit = right if lid is not None else left
            if ref.get("kind") == "ref":
                self.notes.append(
                    f"'{{{ref['id']}}} = {str(lit['value']).lower()}' read as answered / "
                    "not answered"
                )
                ans = {"kind": "answered", "ref": ref}
                positive = bool(lit["value"]) == (op == "==")
                return ans if positive else {"kind": "not", "arg": ans}
        return {"kind": "compare", "op": op, "left": left, "right": right}

    def _set_op(self, word: str, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        rid = self._ref_id(left)
        if rid is None:
            raise _Unsupported(f"{word} needs a question on its left")
        items = right["items"] if right.get("kind") == "__array" else [right]
        for it in items:
            if it.get("kind") not in ("text", "int", "decimal", "bool"):
                raise _Unsupported(f"{word} needs literal values")
        qtype = self.types.get(rid)
        if qtype == "multi":
            tests = [
                {"kind": "contains", "ref": left, "value": self._literal_for(rid, it)}
                for it in items
            ]
        elif qtype in ("single", "text", "integer", "decimal", "date", "slider", "computed", None):
            if word in ("contains", "notcontains") and qtype not in ("single",):
                raise _Unsupported(
                    f"{word} on a {qtype or 'non-choice'} question (substring tests) is not "
                    "supported"
                )
            tests = [
                {"kind": "compare", "op": "==", "left": left, "right": self._literal_for(rid, it)}
                for it in items
            ]
        else:
            raise _Unsupported(f"{word} on a {qtype} question is not supported")
        if word == "allof":
            return tests[0] if len(tests) == 1 else {"kind": "and", "args": tests}
        joined = tests[0] if len(tests) == 1 else {"kind": "or", "args": tests}
        return {"kind": "not", "arg": joined} if word == "notcontains" else joined


def _number(text: str) -> dict[str, Any]:
    if "." in text:
        try:
            return {"kind": "decimal", "value": str(Decimal(text))}
        except InvalidOperation as exc:  # pragma: no cover - the regex rules this out
            raise _Unsupported("bad number") from exc
    return {"kind": "int", "value": int(text)}


def _unquote(text: str) -> str:
    inner = text[1:-1]
    return re.sub(r"\\(.)", r"\1", inner)


def _is_condition(e: dict[str, Any]) -> bool:
    return e.get("kind") in ("compare", "and", "or", "not", "answered", "contains", "bool")


def parse_expression(
    src: str,
    names: dict[str, str],
    types: dict[str, str],
    values: dict[str, dict[str, int | str]],
    value: bool = False,
) -> ExprResult:
    """Convert ``src``. ``names`` maps SurveyJS names (and ``grid.row``) to our ids,
    ``types`` our id → our type, ``values`` our id → {literal text: our choice value}.
    With ``value=False`` the result must be a condition (boolean)."""
    try:
        p = _Parser(_tokens(src), names, types, values)
        expr = p.parse()
    except _Unsupported as exc:
        return ExprResult(None, str(exc))
    except RecursionError:
        return ExprResult(None, "expression is nested too deeply")
    if expr.get("kind") == "__array":
        return ExprResult(None, "an array is not a value")
    if not value and not _is_condition(expr):
        if expr.get("kind") == "ref":
            # SurveyJS: a bare {q} in visibleIf is truthy when answered (and not false/0).
            return ExprResult(
                {"kind": "answered", "ref": expr}, notes=["a bare {question} is read as 'answered'"]
            )
        return ExprResult(None, "not a true/false expression")
    return ExprResult(expr, notes=p.notes)


__all__ = ["SJS_PIPE", "ExprResult", "parse_expression"]
