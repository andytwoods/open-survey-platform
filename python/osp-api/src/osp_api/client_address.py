"""The participant's address, for the in-memory rate limiter only (planning/pages-split.md
D13). Never stored or logged (runtime-design §7).

Behind a host every request comes from the host's own address, so all participants would
share one rate-limit budget. ``OSP_TRUSTED_PROXIES`` (comma-separated IPs or CIDRs, default
empty) names the proxies whose ``X-Forwarded-For`` osp-api believes:

- the direct peer is not in the list: the peer's address, and ``X-Forwarded-For`` is
  ignored (a browser can send anything there);
- it is: walk ``X-Forwarded-For`` from the right, skipping trusted hops, and take the first
  untrusted one (the right-most untrusted hop). The left part of the header is whatever the
  client said and is never used. A malformed hop stops the walk at the last good address.

The key for an IPv6 address is its /64 network: one home or phone network gets one /64 and
can pick any address inside it, so per-address keys would not limit anything.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Sequence

from starlette.requests import Request

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
MAX_HOPS = 32  # longer X-Forwarded-For chains are cut (from the right) at this many hops
IPV6_PREFIX = 64


class TrustedProxiesError(ValueError):
    """``OSP_TRUSTED_PROXIES`` holds something that is not an IP address or CIDR."""


def parse_trusted_proxies(text: str | Iterable[str]) -> tuple[IPNetwork, ...]:
    parts = text.split(",") if isinstance(text, str) else list(text)
    out: list[IPNetwork] = []
    for part in (p.strip() for p in parts):
        if not part:
            continue
        try:
            out.append(_unmap_net(ipaddress.ip_network(part, strict=False)))
        except ValueError:
            raise TrustedProxiesError(
                f"OSP_TRUSTED_PROXIES takes IP addresses or CIDRs, not {part[:60]!r}"
            ) from None
    return tuple(out)


def _unmap_net(net: IPNetwork) -> IPNetwork:
    if isinstance(net, ipaddress.IPv6Network) and net.network_address.ipv4_mapped is not None:
        mapped = net.network_address.ipv4_mapped
        return ipaddress.IPv4Network((mapped, max(0, net.prefixlen - 96)), strict=False)
    return net


def _ip(text: str | None) -> IPAddress | None:
    """An address as a proxy writes it: ``1.2.3.4``, ``::1``, ``[::1]``, ``[::1]:443`` or
    ``1.2.3.4:5678``; IPv4-mapped IPv6 becomes IPv4. Anything else is None."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("["):
        end = s.find("]")
        if end < 0:
            return None
        s = s[1:end]
    elif s.count(":") == 1:  # IPv4 with a port (an IPv6 address has at least two colons)
        s = s.split(":", 1)[0]
    try:
        addr = ipaddress.ip_address(s)
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _trusted(addr: IPAddress, proxies: Sequence[IPNetwork]) -> bool:
    return any(addr.version == net.version and addr in net for net in proxies)


def forwarded_client(
    peer: str | None, forwarded_for: Sequence[str], proxies: Sequence[IPNetwork]
) -> IPAddress | None:
    """The client's address: ``peer``, or (only if ``peer`` is a trusted proxy) the
    right-most untrusted hop of ``X-Forwarded-For`` (all header lines, in order)."""
    addr = _ip(peer)
    if addr is None or not proxies or not _trusted(addr, proxies):
        return addr
    hops = [h for line in forwarded_for for h in line.split(",")][-MAX_HOPS:]
    for hop in reversed(hops):
        if not _trusted(addr, proxies):
            break
        nxt = _ip(hop)
        if nxt is None:
            break  # garbage: keep the last address a trusted proxy vouched for
        addr = nxt
    return addr


def rate_limit_key(addr: IPAddress | None) -> str | None:
    """IPv4: the address. IPv6: its /64 network."""
    if addr is None:
        return None
    if isinstance(addr, ipaddress.IPv6Address):
        return str(ipaddress.IPv6Network((addr, IPV6_PREFIX), strict=False))
    return str(addr)


def client_key(request: Request) -> str | None:
    """The rate-limit key for this request (memory only, never stored)."""
    proxies: Sequence[IPNetwork] = getattr(request.app.state, "trusted_proxies", ()) or ()
    peer = request.client.host if request.client else None
    addr = forwarded_client(peer, request.headers.getlist("x-forwarded-for"), proxies)
    return rate_limit_key(addr) if addr is not None else peer  # e.g. a Unix socket name
