"""RFC 6902 JSON Patch: a structural diff and an applier, for plain JSON values.

`diff(a, b)` returns a patch that turns `a` into `b`. It keeps patches small for the
edits ops make: a changed key is replaced, a list insert/remove is one `add`/`remove`,
and a single element moved within a list is one `move`. Equality is type-strict, so
`1`, `1.0` and `true` are different values (Python would call them equal).

`apply(doc, patch)` returns a new document and never mutates its input. A bad patch
raises `PatchError`; the registry turns that into a diagnostic.
"""

from __future__ import annotations

import copy
from typing import Any

type Json = Any
type Patch = list[dict[str, Any]]


class PatchError(ValueError):
    """The patch is malformed or does not apply to the document."""


# --- equality and pointers ------------------------------------------------------------


def same(a: Json, b: Json) -> bool:
    """Type-strict JSON equality (`1 != 1.0 != True`)."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def to_pointer(parts: tuple[str | int, ...] | list[str | int]) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def from_pointer(ptr: str) -> list[str]:
    if ptr == "":
        return []
    if not ptr.startswith("/"):
        raise PatchError(f"JSON pointer must start with '/': {ptr[:60]!r}")
    return [p.replace("~1", "/").replace("~0", "~") for p in ptr[1:].split("/")]


# --- diff -----------------------------------------------------------------------------


def diff(a: Json, b: Json) -> Patch:
    out: Patch = []
    _diff(a, b, (), out)
    return out


def _diff(a: Json, b: Json, path: tuple[str | int, ...], out: Patch) -> None:
    if same(a, b):
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k not in b:
                out.append({"op": "remove", "path": to_pointer((*path, k))})
        for k in b:
            if k in a:
                _diff(a[k], b[k], (*path, k), out)
            else:
                out.append({"op": "add", "path": to_pointer((*path, k)), "value": _c(b[k])})
        return
    if isinstance(a, list) and isinstance(b, list):
        _diff_list(a, b, path, out)
        return
    out.append({"op": "replace", "path": to_pointer(path), "value": _c(b)})


def _diff_list(a: list[Json], b: list[Json], path: tuple[str | int, ...], out: Patch) -> None:
    start = 0
    while start < len(a) and start < len(b) and same(a[start], b[start]):
        start += 1
    end_a, end_b = len(a), len(b)
    while end_a > start and end_b > start and same(a[end_a - 1], b[end_b - 1]):
        end_a -= 1
        end_b -= 1
    mid_a, mid_b = a[start:end_a], b[start:end_b]
    n = len(mid_a)
    if n == len(mid_b) and n >= 2:
        last = start + n - 1
        if same(mid_a[0], mid_b[-1]) and all(
            same(x, y) for x, y in zip(mid_a[1:], mid_b[:-1], strict=True)
        ):
            out.append(_move(path, start, last))
            return
        if same(mid_a[-1], mid_b[0]) and all(
            same(x, y) for x, y in zip(mid_a[:-1], mid_b[1:], strict=True)
        ):
            out.append(_move(path, last, start))
            return
    common = min(n, len(mid_b))
    for i in range(common):
        _diff(mid_a[i], mid_b[i], (*path, start + i), out)
    for _ in range(common, n):
        out.append({"op": "remove", "path": to_pointer((*path, start + common))})
    for i in range(common, len(mid_b)):
        out.append({"op": "add", "path": to_pointer((*path, start + i)), "value": _c(mid_b[i])})


def _move(path: tuple[str | int, ...], src: int, dst: int) -> dict[str, Any]:
    return {"op": "move", "from": to_pointer((*path, src)), "path": to_pointer((*path, dst))}


def _c(v: Json) -> Json:
    return copy.deepcopy(v)


# --- apply ----------------------------------------------------------------------------

_MAX_OPS = 10_000


def apply(doc: Json, patch: Any) -> Json:
    """Apply an RFC 6902 patch to a copy of `doc`. Raises `PatchError`."""
    if not isinstance(patch, list):
        raise PatchError("a patch is a list of operations")
    if len(patch) > _MAX_OPS:
        raise PatchError(f"a patch may have at most {_MAX_OPS} operations")
    root = [copy.deepcopy(doc)]  # wrapper so the document root is replaceable
    for i, op in enumerate(patch):
        try:
            _apply_one(root, op)
        except PatchError as e:
            raise PatchError(f"operation {i}: {e}") from None
    return root[0]


def _apply_one(root: list[Json], op: Any) -> None:
    if not isinstance(op, dict) or not isinstance(op.get("op"), str):
        raise PatchError("each operation is an object with an 'op' string")
    kind = op["op"]
    path = _str_field(op, "path")
    if kind == "add":
        _add(root, path, _value(op))
    elif kind == "remove":
        _remove(root, path)
    elif kind == "replace":
        value = _value(op)
        if path == "":
            root[0] = value
        else:
            _remove(root, path)
            _add(root, path, value)
    elif kind == "move":
        src = _str_field(op, "from")
        if path != src and (path + "/").startswith(src + "/"):
            raise PatchError("cannot move a value into itself")
        value = _remove(root, src)
        _add(root, path, value)
    elif kind == "copy":
        _add(root, path, copy.deepcopy(_get(root, _str_field(op, "from"))))
    elif kind == "test":
        if not same(_get(root, path), _value(op)):
            raise PatchError(f"test failed at {path[:80]!r}")
    else:
        raise PatchError(f"unknown patch op {kind[:20]!r}")


def _str_field(op: dict[str, Any], key: str) -> str:
    v = op.get(key)
    if not isinstance(v, str):
        raise PatchError(f"'{key}' must be a JSON pointer string")
    return v


def _value(op: dict[str, Any]) -> Json:
    if "value" not in op:
        raise PatchError("'value' is missing")
    return copy.deepcopy(op["value"])


def _parent(root: list[Json], ptr: str) -> tuple[Json, str | int]:
    parts = from_pointer(ptr)
    cur: Json = root
    key: str | int = 0
    for part in parts:
        cur = _step(cur, key)
        key = part
    return cur, key


def _step(cur: Json, key: str | int) -> Json:
    if isinstance(cur, dict):
        if not isinstance(key, str) or key not in cur:
            raise PatchError(f"no member {str(key)[:40]!r}")
        return cur[key]
    if isinstance(cur, list):
        return cur[_index(cur, key, allow_end=False)]
    raise PatchError("path goes through a scalar")


def _index(lst: list[Json], key: str | int, *, allow_end: bool) -> int:
    if isinstance(key, int):
        i = key
    elif key == "-" and allow_end:
        return len(lst)
    elif key.isdigit() and (key == "0" or not key.startswith("0")) and len(key) < 10:
        i = int(key)
    else:
        raise PatchError(f"bad array index {str(key)[:20]!r}")
    if i > len(lst) or (i == len(lst) and not allow_end):
        raise PatchError(f"array index {i} out of range")
    return i


def _get(root: list[Json], ptr: str) -> Json:
    parent, key = _parent(root, ptr)
    return _step(parent, key)


def _add(root: list[Json], ptr: str, value: Json) -> None:
    parent, key = _parent(root, ptr)
    if isinstance(parent, dict):
        parent[str(key)] = value
    elif isinstance(parent, list):
        if parent is root:
            root[0] = value
        else:
            parent.insert(_index(parent, key, allow_end=True), value)
    else:
        raise PatchError("cannot add into a scalar")


def _remove(root: list[Json], ptr: str) -> Json:
    if ptr == "":
        raise PatchError("cannot remove the document root")
    parent, key = _parent(root, ptr)
    if isinstance(parent, dict):
        if key not in parent:
            raise PatchError(f"no member {str(key)[:40]!r}")
        return parent.pop(str(key))
    if isinstance(parent, list):
        return parent.pop(_index(parent, key, allow_end=False))
    raise PatchError("cannot remove from a scalar")
