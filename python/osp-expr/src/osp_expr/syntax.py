"""Text syntax for expressions: a hand-written recursive-descent parser and a printer.

Grammar (lowest precedence first)::

    expr     := or
    or       := and ("or" and)*                 n-ary Or
    and      := not ("and" not)*                n-ary And
    not      := "not" not | compare
    compare  := sum (CMP sum)?                  CMP: == != < <= > >=  (no chaining)
    sum      := product (("+" | "-") product)*  left-associative
    product  := unary (("*" | "/") unary)*      left-associative
    unary    := "-" NUMBER | primary            minus only on numeric literals
    primary  := NUMBER | STRING | "null" | IDENT
              | "answered" "(" IDENT ")"
              | "contains" "(" IDENT "," expr ")"
              | "(" expr ")"

    NUMBER   := digits ("." digits)?            "." makes it a decimal
    STRING   := '"' (char | \\" | \\\\ | \\n | \\r | \\t | \\uXXXX)* '"'
    IDENT    := [A-Za-z_][A-Za-z0-9_]*          not a keyword (and or not null true false)

Example: ``q3 > 5 and contains(q7, "b")``.

``to_text(parse(s).expr)`` is the canonical form of ``s`` (single spaces, minimal
parentheses, ``"``-quoted strings) and ``parse(to_text(e)).expr == e``. ``parse`` never
raises: problems come back as ``Diagnostic``\\ s with character offsets.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from .ast import (
    KEYWORDS,
    And,
    Answered,
    Arith,
    Compare,
    Contains,
    DecLit,
    Expr,
    IntLit,
    Not,
    NullLit,
    Or,
    Ref,
    TextLit,
)
from .diagnostics import Diagnostic

MAX_DEPTH = 64
"""Deepest AST the parser builds; deeper input gets a ``too-deep`` diagnostic."""

MAX_INT_DIGITS = 1000
"""Longest integer literal accepted (Python refuses to convert very long digit strings)."""

FUNCTIONS = ("answered", "contains")


class ParseResult(BaseModel):
    """``expr`` is set iff there are no error diagnostics."""

    model_config = ConfigDict(frozen=True)

    expr: Expr | None
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def ok(self) -> bool:
        return self.expr is not None


# --- Lexer ------------------------------------------------------------------------


@dataclass(frozen=True)
class _Tok:
    kind: str  # int | dec | str | ident | kw | op | eof
    text: str  # source text (for str: the decoded value)
    start: int
    end: int


class _SyntaxError(Exception):
    def __init__(self, code: str, message: str, start: int, end: int):
        super().__init__(message)
        self.diag = Diagnostic(code=code, message=message, start=start, end=end)


_TWO_CHAR_OPS = ("==", "!=", "<=", ">=")
_ONE_CHAR_OPS = "<>+-*/(),"
_HEX = "0123456789abcdefABCDEF"
_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "r": "\r", "t": "\t"}
_HINTS = {
    "=": "use '==' to test equality",
    "!": "use '!=' or 'not'",
    "&&": "use 'and'",
    "||": "use 'or'",
    "&": "use 'and'",
    "|": "use 'or'",
    "'": "text literals use double quotes",
}


def _is_ident_start(c: str) -> bool:
    return c == "_" or ("a" <= c <= "z") or ("A" <= c <= "Z")


def _is_ident_char(c: str) -> bool:
    return _is_ident_start(c) or ("0" <= c <= "9")


def _is_digit(c: str) -> bool:
    return "0" <= c <= "9"


def _lex(src: str) -> list[_Tok]:
    toks: list[_Tok] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c in " \t\r\n":
            i += 1
            continue
        start = i
        if _is_digit(c):
            while i < n and _is_digit(src[i]):
                i += 1
            kind = "int"
            if i < n and src[i] == ".":
                if i + 1 < n and _is_digit(src[i + 1]):
                    i += 1
                    while i < n and _is_digit(src[i]):
                        i += 1
                    kind = "dec"
                else:
                    raise _SyntaxError(
                        "bad-number", "a decimal point must be followed by digits", start, i + 1
                    )
            if i < n and (_is_ident_char(src[i]) or src[i] == "."):
                j = i
                while j < n and (_is_ident_char(src[j]) or src[j] == "."):
                    j += 1
                raise _SyntaxError("bad-number", "malformed number", start, j)
            if kind == "int" and i - start > MAX_INT_DIGITS:
                raise _SyntaxError(
                    "bad-number", f"integer literal longer than {MAX_INT_DIGITS} digits", start, i
                )
            toks.append(_Tok(kind, src[start:i], start, i))
            continue
        if _is_ident_start(c):
            while i < n and _is_ident_char(src[i]):
                i += 1
            word = src[start:i]
            toks.append(_Tok("kw" if word in KEYWORDS else "ident", word, start, i))
            continue
        if c == '"':
            i += 1
            out: list[str] = []
            while True:
                if i >= n:
                    raise _SyntaxError("unterminated-text", "text literal is not closed", start, n)
                ch = src[i]
                if ch == '"':
                    i += 1
                    break
                if ch == "\\":
                    if i + 1 >= n:
                        raise _SyntaxError("bad-escape", "unfinished escape", i, n)
                    e = src[i + 1]
                    if e in _ESCAPES:
                        out.append(_ESCAPES[e])
                        i += 2
                        continue
                    if e == "u":
                        hexpart = src[i + 2 : i + 6]
                        if len(hexpart) == 4 and all(
                            h in "0123456789abcdefABCDEF" for h in hexpart
                        ):
                            out.append(chr(int(hexpart, 16)))
                            i += 6
                            continue
                        raise _SyntaxError(
                            "bad-escape", "\\u must be followed by 4 hex digits", i, min(i + 6, n)
                        )
                    raise _SyntaxError("bad-escape", f"unknown escape '\\{e}'", i, i + 2)
                out.append(ch)
                i += 1
            toks.append(_Tok("str", "".join(out), start, i))
            continue
        two = src[i : i + 2]
        if two in _TWO_CHAR_OPS:
            toks.append(_Tok("op", two, i, i + 2))
            i += 2
            continue
        if len(two) == 2 and two in _HINTS:
            raise _SyntaxError("unexpected-char", f"unexpected '{two}': {_HINTS[two]}", i, i + 2)
        if c in _ONE_CHAR_OPS:
            toks.append(_Tok("op", c, i, i + 1))
            i += 1
            continue
        hint = f": {_HINTS[c]}" if c in _HINTS else ""
        raise _SyntaxError("unexpected-char", f"unexpected character {c!r}{hint}", i, i + 1)
    toks.append(_Tok("eof", "", n, n))
    return toks


# --- Parser -----------------------------------------------------------------------

_CMP_OPS = ("==", "!=", "<", "<=", ">", ">=")


class _Parser:
    def __init__(self, toks: list[_Tok]):
        self.toks = toks
        self.pos = 0
        self.nesting = 0

    # helpers
    def peek(self) -> _Tok:
        return self.toks[self.pos]

    def advance(self) -> _Tok:
        tok = self.toks[self.pos]
        if tok.kind != "eof":
            self.pos += 1
        return tok

    def at(self, kind: str, text: str | None = None) -> bool:
        tok = self.peek()
        return tok.kind == kind and (text is None or tok.text == text)

    def expect_op(self, text: str, what: str) -> _Tok:
        tok = self.peek()
        if tok.kind == "op" and tok.text == text:
            return self.advance()
        raise _SyntaxError(
            "expected", f"expected '{text}' {what}, found {_describe(tok)}", *_span(tok)
        )

    def check_depth(self, depth: int, start: int) -> int:
        if depth > MAX_DEPTH:
            raise _SyntaxError(
                "too-deep",
                f"expression is nested more than {MAX_DEPTH} levels deep",
                start,
                self.peek().end,
            )
        return depth

    # grammar; each rule returns (node, depth)
    def parse(self) -> Expr:
        node, _ = self.or_()
        tok = self.peek()
        if tok.kind != "eof":
            raise _SyntaxError(
                "unexpected", f"unexpected {_describe(tok)} after expression", *_span(tok)
            )
        return node

    def or_(self) -> tuple[Expr, int]:
        start = self.peek().start
        first = self.and_()
        args = [first]
        while self.at("kw", "or"):
            self.advance()
            args.append(self.and_())
        if len(args) == 1:
            return first
        depth = self.check_depth(1 + max(d for _, d in args), start)
        return Or(args=tuple(a for a, _ in args)), depth

    def and_(self) -> tuple[Expr, int]:
        start = self.peek().start
        first = self.not_()
        args = [first]
        while self.at("kw", "and"):
            self.advance()
            args.append(self.not_())
        if len(args) == 1:
            return first
        depth = self.check_depth(1 + max(d for _, d in args), start)
        return And(args=tuple(a for a, _ in args)), depth

    def not_(self) -> tuple[Expr, int]:
        if self.at("kw", "not"):
            start = self.advance().start
            self.nesting += 1
            self.check_depth(self.nesting, start)
            arg, d = self.not_()
            self.nesting -= 1
            return Not(arg=arg), self.check_depth(d + 1, start)
        return self.compare()

    def compare(self) -> tuple[Expr, int]:
        start = self.peek().start
        left, ld = self.sum_()
        tok = self.peek()
        if tok.kind == "op" and tok.text in _CMP_OPS:
            self.advance()
            right, rd = self.sum_()
            nxt = self.peek()
            if nxt.kind == "op" and nxt.text in _CMP_OPS:
                raise _SyntaxError(
                    "chained-comparison",
                    "comparisons cannot be chained; combine them with 'and'",
                    *_span(nxt),
                )
            node = Compare(op=tok.text, left=left, right=right)  # type: ignore[arg-type]
            return node, self.check_depth(1 + max(ld, rd), start)
        return left, ld

    def sum_(self) -> tuple[Expr, int]:
        start = self.peek().start
        left, ld = self.product()
        while self.peek().kind == "op" and self.peek().text in ("+", "-"):
            op = self.advance().text
            right, rd = self.product()
            ld = self.check_depth(1 + max(ld, rd), start)
            left = Arith(op=op, left=left, right=right)  # type: ignore[arg-type]
        return left, ld

    def product(self) -> tuple[Expr, int]:
        start = self.peek().start
        left, ld = self.unary()
        while self.peek().kind == "op" and self.peek().text in ("*", "/"):
            op = self.advance().text
            right, rd = self.unary()
            ld = self.check_depth(1 + max(ld, rd), start)
            left = Arith(op=op, left=left, right=right)  # type: ignore[arg-type]
        return left, ld

    def unary(self) -> tuple[Expr, int]:
        if self.at("op", "-"):
            minus = self.advance()
            tok = self.peek()
            if tok.kind in ("int", "dec"):
                self.advance()
                return _number(tok, negative=True), 1
            raise _SyntaxError(
                "unary-minus",
                "'-' can only prefix a number; write '0 - x' to negate an expression",
                minus.start,
                tok.end,
            )
        return self.primary()

    def primary(self) -> tuple[Expr, int]:
        tok = self.peek()
        if tok.kind in ("int", "dec"):
            self.advance()
            return _number(tok, negative=False), 1
        if tok.kind == "str":
            self.advance()
            return TextLit(value=tok.text), 1
        if tok.kind == "kw":
            if tok.text == "null":
                self.advance()
                return NullLit(), 1
            if tok.text in ("true", "false"):
                raise _SyntaxError(
                    "reserved-word",
                    f"'{tok.text}' is reserved; boolean literals are not supported",
                    *_span(tok),
                )
            raise _SyntaxError("expected", f"expected a value, found {_describe(tok)}", *_span(tok))
        if tok.kind == "ident":
            self.advance()
            if self.at("op", "("):
                return self.call(tok)
            return Ref(id=tok.text), 1
        if tok.kind == "op" and tok.text == "(":
            self.advance()
            self.nesting += 1
            self.check_depth(self.nesting, tok.start)
            node, d = self.or_()
            self.nesting -= 1
            self.expect_op(")", "to close '('")
            return node, d
        raise _SyntaxError("expected", f"expected a value, found {_describe(tok)}", *_span(tok))

    def call(self, name: _Tok) -> tuple[Expr, int]:
        if name.text not in FUNCTIONS:
            raise _SyntaxError(
                "unknown-function",
                f"unknown function '{name.text}' (known: {', '.join(FUNCTIONS)})",
                *_span(name),
            )
        self.advance()  # "("
        ref = self.ref_arg(name.text)
        if name.text == "answered":
            self.expect_op(")", "to close answered(")
            return Answered(ref=ref), 2
        self.expect_op(",", "between the arguments of contains(")
        self.nesting += 1
        self.check_depth(self.nesting, name.start)
        value, d = self.or_()
        self.nesting -= 1
        self.expect_op(")", "to close contains(")
        return Contains(ref=ref, value=value), self.check_depth(d + 1, name.start)

    def ref_arg(self, fn: str) -> Ref:
        tok = self.peek()
        if tok.kind == "ident":
            self.advance()
            return Ref(id=tok.text)
        raise _SyntaxError(
            "expected-question",
            f"the first argument of {fn}() must be a question id, found {_describe(tok)}",
            *_span(tok),
        )


def _span(tok: _Tok) -> tuple[int, int]:
    return tok.start, tok.end


def _describe(tok: _Tok) -> str:
    if tok.kind == "eof":
        return "end of input"
    if tok.kind == "str":
        return "text literal"
    return f"'{tok.text}'"


def _number(tok: _Tok, *, negative: bool) -> Expr:
    sign = "-" if negative else ""
    if tok.kind == "int":
        return IntLit(value=int(sign + tok.text))
    return DecLit(value=Decimal(sign + tok.text))


def parse(src: str) -> ParseResult:
    """Parse expression text. Never raises; errors come back as diagnostics."""
    try:
        if not isinstance(src, str):
            return _fail("not-text", "expression source must be text", None, None)
        toks = _lex(src)
        expr = _Parser(toks).parse()
        return ParseResult(expr=expr)
    except _SyntaxError as e:
        return ParseResult(expr=None, diagnostics=(e.diag,))
    except Exception as e:  # last-resort guard: parse must never raise
        return _fail("internal", f"could not parse expression: {type(e).__name__}", 0, None)


def _fail(code: str, message: str, start: int | None, end: int | None) -> ParseResult:
    return ParseResult(
        expr=None, diagnostics=(Diagnostic(code=code, message=message, start=start, end=end),)
    )


# --- Printer ----------------------------------------------------------------------

_P_OR, _P_AND, _P_NOT, _P_CMP, _P_SUM, _P_PROD, _P_ATOM = range(1, 8)


def _prec(node: Expr) -> int:
    match node:
        case Or():
            return _P_OR
        case And():
            return _P_AND
        case Not():
            return _P_NOT
        case Compare():
            return _P_CMP
        case Arith(op="+" | "-"):
            return _P_SUM
        case Arith():
            return _P_PROD
        case _:
            return _P_ATOM


def _text_literal(value: str) -> str:
    out = ['"']
    for ch in value:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _decimal_literal(value: Decimal) -> str:
    text = format(value, "f")
    return text if "." in text else text + ".0"


def _print(node: Expr, min_prec: int) -> str:
    match node:
        case IntLit(value=v):
            text = str(v)
        case DecLit(value=v):
            text = _decimal_literal(v)
        case TextLit(value=v):
            text = _text_literal(v)
        case NullLit():
            text = "null"
        case Ref(id=i):
            text = i
        case Answered(ref=r):
            text = f"answered({r.id})"
        case Contains(ref=r, value=v):
            text = f"contains({r.id}, {_print(v, _P_OR)})"
        case Or(args=args):
            text = " or ".join(_print(a, _P_AND) for a in args)
        case And(args=args):
            text = " and ".join(_print(a, _P_NOT) for a in args)
        case Not(arg=a):
            text = "not " + _print(a, _P_NOT)
        case Compare(op=op, left=l, right=r):
            text = f"{_print(l, _P_SUM)} {op} {_print(r, _P_SUM)}"
        case Arith(op=op, left=l, right=r):
            p = _prec(node)
            text = f"{_print(l, p)} {op} {_print(r, p + 1)}"
        case _:  # pragma: no cover - exhaustive over Expr
            raise TypeError(f"not an expression node: {node!r}")
    return f"({text})" if _prec(node) < min_prec else text


def to_text(expr: Expr) -> str:
    """Print an expression in canonical text syntax."""
    return _print(expr, _P_OR)


__all__ = ["MAX_DEPTH", "FUNCTIONS", "ParseResult", "parse", "to_text"]
