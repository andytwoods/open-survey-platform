"""LimeSurvey Expression Manager text → osp-expr JSON (the subset our model can express).

From the public Expression Manager documentation: question codes with optional suffixes
(``Q1``, ``Q1.NAOK``, ``Q1.shown``, ``Q1.value``, ``Q1.code``), subquestion codes
(``Q1_SQ001``), SGQA codes (``123X4X56``), operators ``== != < <= > >=`` (also ``eq ne
lt le gt ge``), ``and`` / ``&&``, ``or`` / ``||``, ``!``, arithmetic ``+ - * /``, and
the functions ``is_empty``, ``if``, ``intval``, ``floatval``, ``strtotime``. Anything
else (``rand``, ``fmod``, ``count``, ``sum``, ``join`` …) makes the whole expression
unconvertible; the caller reports it as a loss. Clean-room: no LimeSurvey code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

_TOKEN = re.compile(
    r"""\s*(?:
    (?P<sgqa>\d+X\d+X\d+[A-Za-z0-9_]*(?:\.[A-Za-z]+)?)|
    (?P<num>\d+(?:\.\d+)?)|
    (?P<str>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")|
    (?P<op><=|>=|==|!=|<|>|&&|\|\||[()+\-*/,!])|
    (?P<word>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z]+)?)
    )""",
    re.VERBOSE,
)
_SGQA = re.compile(r"^(\d+)X(\d+)X(\d+)(.*)$")

_COMPARE = {
    "==": "==",
    "eq": "==",
    "!=": "!=",
    "ne": "!=",
    "<": "<",
    "lt": "<",
    "<=": "<=",
    "le": "<=",
    ">": ">",
    "gt": ">",
    ">=": ">=",
    "ge": ">=",
}


class _Unsupported(Exception):
    pass


@dataclass
class EMResult:
    expr: dict[str, Any] | None
    reason: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class EMNames:
    """How codes resolve.

    - ``codes``: LimeSurvey question code → our id (also ``<code>_<sub>`` for a matrix row).
    - ``qids``: LimeSurvey qid → question code (for SGQA references).
    - ``types``: our id → our type; ``multi_codes``: our multi id → {subquestion code: value}.
    - ``values``: our choice id → {answer code: our value}.
    """

    codes: dict[str, str]
    qids: dict[str, str]
    types: dict[str, str]
    multi_codes: dict[str, dict[str, int | str]]
    values: dict[str, dict[str, int | str]]


@dataclass
class _Tok:
    kind: str
    text: str


def _tokens(src: str) -> list[_Tok]:
    out: list[_Tok] = []
    pos = 0
    while pos < len(src) and src[pos:].strip():
        m = _TOKEN.match(src, pos)
        if not m or m.end() == pos:
            raise _Unsupported(f"unexpected character {src[pos : pos + 1]!r}")
        pos = m.end()
        kind = m.lastgroup or ""
        out.append(_Tok(kind, m.group(kind)))
    return out


@dataclass
class _Multi:
    """``<multi>_<code>`` read on its own: meaningful only as ``== "Y"`` / ``!= "Y"``."""

    ref: str
    value: int | str


class _Parser:
    def __init__(self, tokens: list[_Tok], names: EMNames) -> None:
        self.t, self.i, self.n = tokens, 0, names
        self.notes: list[str] = []

    def peek(self) -> _Tok | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self) -> _Tok:
        tok = self.peek()
        if tok is None:
            raise _Unsupported("unexpected end of expression")
        self.i += 1
        return tok

    def at(self, *words: str) -> bool:
        tok = self.peek()
        return tok is not None and tok.text.lower() in words

    def parse(self) -> Any:
        e = self.or_()
        if self.peek() is not None:
            raise _Unsupported(f"unexpected {self.peek().text!r}")  # type: ignore[union-attr]
        return e

    def or_(self) -> Any:
        args = [self.and_()]
        while self.at("or", "||"):
            self.take()
            args.append(self.and_())
        if len(args) == 1:
            return args[0]
        kept = [a for a in (self._cond(x) for x in args) if a != {"kind": "bool", "value": False}]
        if any(a == {"kind": "bool", "value": True} for a in kept):
            return {"kind": "bool", "value": True}
        if not kept:
            return {"kind": "bool", "value": False}
        return kept[0] if len(kept) == 1 else {"kind": "or", "args": kept}

    def and_(self) -> Any:
        args = [self.not_()]
        while self.at("and", "&&"):
            self.take()
            args.append(self.not_())
        if len(args) == 1:
            return args[0]
        kept = [a for a in (self._cond(x) for x in args) if a != {"kind": "bool", "value": True}]
        if any(a == {"kind": "bool", "value": False} for a in kept):
            return {"kind": "bool", "value": False}
        if not kept:
            return {"kind": "bool", "value": True}
        return kept[0] if len(kept) == 1 else {"kind": "and", "args": kept}

    def not_(self) -> Any:
        if self.at("!"):
            self.take()
            inner = self._cond(self.not_())
            return inner["arg"] if inner.get("kind") == "not" else {"kind": "not", "arg": inner}
        return self.comparison()

    def comparison(self) -> Any:
        left = self.additive()
        tok = self.peek()
        if tok is not None and tok.text.lower() in _COMPARE:
            self.take()
            right = self.additive()
            return self._compare(_COMPARE[tok.text.lower()], left, right)
        return left

    def additive(self) -> Any:
        e = self.multiplicative()
        while self.at("+", "-"):
            op = self.take().text
            e = {
                "kind": "arith",
                "op": op,
                "left": self._val(e),
                "right": self._val(self.multiplicative()),
            }
        return e

    def multiplicative(self) -> Any:
        e = self.unary()
        while self.at("*", "/"):
            op = self.take().text
            e = {"kind": "arith", "op": op, "left": self._val(e), "right": self._val(self.unary())}
        return e

    def unary(self) -> Any:
        if self.at("-"):
            self.take()
            inner = self.unary()
            if isinstance(inner, dict) and inner.get("kind") == "int":
                return {"kind": "int", "value": -inner["value"]}
            if isinstance(inner, dict) and inner.get("kind") == "decimal":
                return {"kind": "decimal", "value": str(-Decimal(inner["value"]))}
            return {
                "kind": "arith",
                "op": "-",
                "left": {"kind": "int", "value": 0},
                "right": self._val(inner),
            }
        if self.at("+"):
            self.take()
            return self.unary()
        return self.primary()

    def primary(self) -> Any:
        tok = self.take()
        if tok.kind == "num":
            if "." in tok.text:
                return {"kind": "decimal", "value": str(Decimal(tok.text))}
            return {"kind": "int", "value": int(tok.text)}
        if tok.kind == "str":
            return {"kind": "text", "value": re.sub(r"\\(.)", r"\1", tok.text[1:-1])}
        if tok.kind == "op" and tok.text == "(":
            e = self.or_()
            if not self.at(")"):
                raise _Unsupported("missing ')'")
            self.take()
            return e
        if tok.kind == "sgqa":
            return self._ref(tok.text)
        if tok.kind == "word":
            if self.at("("):
                return self._call(tok.text.lower())
            return self._ref(tok.text)
        raise _Unsupported(f"unexpected {tok.text!r}")

    def _call(self, name: str) -> Any:
        self.take()
        args: list[Any] = []
        while not self.at(")"):
            args.append(self.or_())
            if self.at(","):
                self.take()
            elif not self.at(")"):
                raise _Unsupported("bad argument list")
        self.take()
        if name == "is_empty" and len(args) == 1:
            a = args[0]
            if isinstance(a, _Multi):
                return {
                    "kind": "not",
                    "arg": {
                        "kind": "contains",
                        "ref": {"kind": "ref", "id": a.ref},
                        "value": _lit(a.value),
                    },
                }
            if isinstance(a, dict) and a.get("kind") == "ref":
                return {"kind": "not", "arg": {"kind": "answered", "ref": a}}
            raise _Unsupported("is_empty() needs a question")
        if name == "if" and len(args) == 3:
            return {
                "kind": "if",
                "cond": self._cond(args[0]),
                "then": self._val(args[1]),
                "else": self._val(args[2]),
            }
        if name in ("intval", "floatval", "strtotime", "trim") and len(args) == 1:
            if name == "strtotime":
                self.notes.append("dates are compared as text (strtotime dropped)")
            return args[0]
        raise _Unsupported(f"function {name}() is not supported")

    def _ref(self, word: str) -> Any:
        code, _, suffix = word.partition(".")
        if suffix and suffix.lower() not in (
            "naok",
            "shown",
            "value",
            "code",
            "valuenaok",
            "relevancestatus",
        ):
            raise _Unsupported(f"suffix .{suffix} is not supported")
        if suffix.lower() == "shown":
            self.notes.append(f"{word} compares the stored code, not the shown label")
        m = _SGQA.match(code)
        if m:
            qcode = self.n.qids.get(m.group(3))
            if qcode is None:
                raise _Unsupported(f"{code} names no question")
            code = qcode + m.group(4)
        ours = self.n.codes.get(code)
        if ours is not None:
            return {"kind": "ref", "id": ours}
        # <multi code>_<subquestion code>
        head, sep, sub = code.rpartition("_")
        while sep:
            mid = self.n.codes.get(head)
            if mid is not None and self.n.types.get(mid) == "multi":
                value = self.n.multi_codes.get(mid, {}).get(sub)
                if value is not None:
                    return _Multi(mid, value)
            head, sep, sub2 = head.rpartition("_")
            sub = sub2 + "_" + sub
        raise _Unsupported(f"{code} names no imported question")

    def _lit_for(self, rid: str, lit: dict[str, Any]) -> dict[str, Any]:
        mapping = self.n.values.get(rid)
        if mapping is None or lit.get("kind") not in ("text", "int", "decimal"):
            return lit
        v = mapping.get(str(lit["value"]))
        if v is None:
            return lit
        return _lit(v)

    def _compare(self, op: str, left: Any, right: Any) -> dict[str, Any]:
        if isinstance(left, _Multi) or isinstance(right, _Multi):
            m, other = (left, right) if isinstance(left, _Multi) else (right, left)
            if (
                isinstance(other, dict)
                and other.get("kind") == "text"
                and other["value"] in ("Y", "")
                and op in ("==", "!=")
            ):
                checked = {
                    "kind": "contains",
                    "ref": {"kind": "ref", "id": m.ref},
                    "value": _lit(m.value),
                }
                positive = (other["value"] == "Y") == (op == "==")
                return checked if positive else {"kind": "not", "arg": checked}
            raise _Unsupported('a multiple-choice column can only be compared with "Y"')
        lid = left.get("id") if isinstance(left, dict) and left.get("kind") == "ref" else None
        rid = right.get("id") if isinstance(right, dict) and right.get("kind") == "ref" else None
        if lid is not None and isinstance(right, dict):
            right = self._lit_for(lid, right)
        elif rid is not None and isinstance(left, dict):
            left = self._lit_for(rid, left)
        if (
            isinstance(right, dict)
            and right.get("kind") == "text"
            and right["value"] == ""
            and lid is not None
            and op in ("==", "!=")
        ):
            ans = {"kind": "answered", "ref": left}
            return {"kind": "not", "arg": ans} if op == "==" else ans
        return {"kind": "compare", "op": op, "left": self._val(left), "right": self._val(right)}

    def _cond(self, e: Any) -> dict[str, Any]:
        if isinstance(e, _Multi):
            return {"kind": "contains", "ref": {"kind": "ref", "id": e.ref}, "value": _lit(e.value)}
        if e.get("kind") == "int" and e["value"] in (0, 1):
            return {"kind": "bool", "value": e["value"] == 1}
        if e.get("kind") == "ref":
            return {"kind": "answered", "ref": e}
        if e.get("kind") in ("compare", "and", "or", "not", "answered", "contains", "bool", "if"):
            return e
        raise _Unsupported("not a true/false expression")

    def _val(self, e: Any) -> dict[str, Any]:
        if isinstance(e, _Multi):
            raise _Unsupported("a multiple-choice column is not a value")
        if e.get("kind") == "text" and e["value"] == "":
            return {"kind": "null"}  # EM's empty string is our missing value
        return e


def _lit(v: int | str) -> dict[str, Any]:
    return {"kind": "int", "value": v} if isinstance(v, int) else {"kind": "text", "value": v}


def parse_em(src: str, names: EMNames, value: bool = False) -> EMResult:
    """Convert an Expression Manager expression (without the braces of a ``{...}`` in a
    question text). ``value=False``: the result must be a condition."""
    try:
        p = _Parser(_tokens(src), names)
        e = p.parse()
        e = p._val(e) if value else p._cond(e)
    except _Unsupported as exc:
        return EMResult(None, str(exc))
    except RecursionError:
        return EMResult(None, "expression is nested too deeply")
    if value and e.get("kind") == "bool":
        return EMResult(e, notes=p.notes)
    return EMResult(e, notes=p.notes)


def strip_guards(src: str) -> str:
    """Our exporter writes constraints as ``is_empty(Q.NAOK) or (<checks>)``: a constraint
    is only checked on answered values here, so the guard is dropped."""
    m = re.match(r"^\s*is_empty\([A-Za-z0-9_.]+\)\s+or\s+(.*)$", src, re.DOTALL)
    return m.group(1) if m else src


_STEP = re.compile(
    r"fmod\(\s*([A-Za-z][A-Za-z0-9_]*)\.NAOK\s*-\s*\((-?[\d.]+)\)\s*,\s*(-?[\d.]+)\s*\)\s*==\s*0"
)
_LATCHED = re.compile(
    r"^if\(\s*!is_empty\(\s*([A-Za-z][A-Za-z0-9_]*)\.NAOK\s*\)\s*,\s*\1\.NAOK\s*,\s*rand\(\s*1\s*,\s*(\d+)\s*\)\s*\)$"
)
_PICK = re.compile(
    r"^if\(\s*([A-Za-z][A-Za-z0-9_]*)\.NAOK\s*==\s*(\d+)\s*,\s*('[^']*'|\"[^\"]*\")\s*,\s*(.*)\)$",
    re.DOTALL,
)


def slider_step(src: str) -> tuple[str, str, str, str] | None:
    """``(code, min, step, rest)`` when the validation holds our exporter's slider step
    check ``fmod(code.NAOK - (min), step) == 0``; ``rest`` is the text with it removed."""
    m = _STEP.search(src)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3), src[: m.start()] + "1" + src[m.end() :]


def latched_draw(src: str, code: str) -> int | None:
    """``N`` when ``src`` is our exporter's latched random draw ``if(!is_empty(code.NAOK),
    code.NAOK, rand(1, N))`` for ``code`` itself."""
    m = _LATCHED.match(src.strip())
    return int(m.group(2)) if m and m.group(1) == code else None


def level_chain(src: str) -> tuple[str, list[str]] | None:
    """``(draw code, levels)`` when ``src`` is our exporter's assignment chain
    ``if(seed.NAOK == 1, "a", if(seed.NAOK == 2, "b", ""))``."""
    levels: list[str] = []
    seed: str | None = None
    rest = src.strip()
    for _ in range(1000):
        m = _PICK.match(rest)
        if not m:
            break
        if seed is None:
            seed = m.group(1)
        elif m.group(1) != seed or int(m.group(2)) != len(levels) + 1:
            return None
        if int(m.group(2)) != len(levels) + 1:
            return None
        levels.append(m.group(3)[1:-1])
        rest = m.group(4).strip()
    if seed is None or rest != '""':
        return None
    return seed, levels


__all__ = [
    "EMNames",
    "EMResult",
    "latched_draw",
    "level_chain",
    "parse_em",
    "slider_step",
    "strip_guards",
]
