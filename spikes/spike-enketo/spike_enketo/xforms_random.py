"""randomize(nodeset, seed) reimplemented from the ODK XForms spec text ONLY (clean-room).

Spec (getodk.github.io/xforms-spec, Functions table, randomize):
  * shuffle with the "inside-out" variant of Fisher-Yates (links Wikipedia);
  * with a seed: same algorithm with a *seeded Park Miller* PRNG;
  * decimal seed -> truncated to whole number;
  * seed NaN when converted to number -> UTF-8 encode, sha256, first 8 bytes as
    signed 64-bit big-endian integer.

The spec does NOT say which Park-Miller constants, how the seed becomes the PRNG
state, or how a PRNG draw becomes an index. Our assumptions (record in FINDINGS):
  A1  "minimal standard" Park & Miller (1988): modulus 2^31-1, multiplier 16807.
  A2  state = seed rem (2^31-1), remainder truncating toward zero (sign of the dividend, as
      in JS/Java `%`); if state <= 0 then state += 2^31-2.  (Spike finding: our first attempt
      used Python's floor-mod and disagreed with Enketo on negative seeds only; `remainder=
      "floor"` keeps that variant for the evidence run.)
  A3  each draw: state = state*16807 mod (2^31-1); u = (state-1)/(2^31-2) in [0,1).
  A4  inside-out step i (0-based): j = floor(u*(i+1)); a[i] = a[j]; a[j] = source[i].
"""

from __future__ import annotations

import hashlib
import math
import struct

M = 2**31 - 1
A = 16807


def seed_to_int(seed: object) -> int:
    """Spec: decimal -> truncate; NaN -> sha256 first 8 bytes (signed BE int64)."""
    if isinstance(seed, (int, float)) and not isinstance(seed, bool):
        num = float(seed)
    else:
        try:
            num = float(str(seed).strip()) if str(seed).strip() != "" else math.nan
        except ValueError:
            num = math.nan
    if math.isnan(num):
        digest = hashlib.sha256(str(seed).encode("utf-8")).digest()
        return struct.unpack(">q", digest[:8])[0]
    if isinstance(seed, int):
        return seed
    return math.trunc(num)


class ParkMiller:
    def __init__(self, seed: int, remainder: str = "trunc") -> None:
        if remainder == "floor":
            s = seed % M
        else:  # A2: truncating remainder (exact for any int, no float rounding)
            s = abs(seed) % M * (1 if seed >= 0 else -1)
        if s <= 0:
            s += M - 1
        self.state = s

    def next_float(self) -> float:  # A3
        self.state = (self.state * A) % M
        return (self.state - 1) / (M - 1)


def randomize[T](items: list[T], seed: object, remainder: str = "trunc") -> list[T]:
    rng = ParkMiller(seed_to_int(seed), remainder)
    out: list[T] = []
    for i, x in enumerate(items):  # A4: inside-out Fisher-Yates
        j = math.floor(rng.next_float() * (i + 1))
        if j == i:
            out.append(x)
        else:
            out.append(out[j])
            out[j] = x
    return out


def substream_seed(survey_version: str, session_seed: int, node_id: str) -> int:
    """semantics.md s7: PRNG(hash(surveyVersion, sessionSeed, nodeId)) -> a positive 31-bit seed."""
    h = hashlib.sha256(f"{survey_version}|{session_seed}|{node_id}".encode()).digest()
    return int.from_bytes(h[:4], "big") % (M - 1) + 1
