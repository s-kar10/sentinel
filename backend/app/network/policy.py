"""Exact origins and explicit private networks; no request-controlled grants."""

from dataclasses import dataclass
from ipaddress import (
    IPv4Address,
    IPv4Network,
    IPv6Address,
    IPv6Network,
    ip_address,
    ip_network,
)

import httpx

Address = IPv4Address | IPv6Address
Network = IPv4Network | IPv6Network
Origin = tuple[str, str, int]
PRIVATE_RANGES = tuple(
    ip_network(value)
    for value in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "::1/128",
        "fc00::/7",
    )
)
# Translation/tunnel addresses must not turn an approved IPv6 route into IPv4 SSRF.
FORBIDDEN = tuple(
    ip_network(value)
    for value in (
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "2002::/16",
        "2001::/32",
        "168.63.129.16/32",
        "fd00:ec2::254/128",
    )
)


class EgressDenied(httpx.RequestError):
    def __init__(self) -> None:
        super().__init__("Outbound destination is not permitted by operator policy.")


def origin(url: httpx.URL) -> Origin:
    if (
        url.scheme not in {"http", "https"}
        or not url.host
        or url.userinfo
        or url.fragment
        or "%" in url.host
        or "\\" in url.host
        or "*" in url.host
        or url.port == 0
    ):
        raise EgressDenied()
    return (
        url.scheme,
        url.raw_host.decode("ascii"),
        url.port or (443 if url.scheme == "https" else 80),
    )


@dataclass(frozen=True)
class DestinationRule:
    origin: Origin
    private_networks: tuple[Network, ...]

    def permits(self, address: Address) -> bool:
        if (
            address.is_unspecified
            or address.is_multicast
            or address.is_link_local
            or (address.is_reserved and not address.is_loopback)
            or (isinstance(address, IPv6Address) and address.ipv4_mapped is not None)
            or any(address in network for network in FORBIDDEN)
        ):
            return False
        return address.is_global or any(
            address in network for network in self.private_networks
        )


class EgressPolicy:
    def __init__(self, rules: dict[str, list[str]]) -> None:
        self.rules: dict[Origin, DestinationRule] = {}
        if len(rules) > 64:
            raise ValueError("At most 64 outbound origins may be configured.")
        for value, cidrs in rules.items():
            try:
                if len(value) > 2048 or len(cidrs) > 16:
                    raise ValueError
                url = httpx.URL(value)
                key = origin(url)
                if url.path != "/" or url.query or key in self.rules:
                    raise ValueError
                networks = tuple(ip_network(cidr, strict=True) for cidr in cidrs)
                if any(
                    not any(
                        network.version == allowed.version
                        and network.subnet_of(allowed)
                        for allowed in PRIVATE_RANGES
                    )
                    for network in networks
                ):
                    raise ValueError
            except (ValueError, httpx.InvalidURL, EgressDenied):
                raise ValueError(
                    "Outbound rules require unique HTTP(S) origins and narrow private/loopback CIDRs."
                ) from None
            self.rules[key] = DestinationRule(key, networks)

    def select(self, url: httpx.URL) -> DestinationRule:
        rule = self.rules.get(origin(url))
        if rule is None:
            raise EgressDenied()
        return rule


def checked_address(value: str, rule: DestinationRule) -> Address:
    try:
        if "%" in value:
            raise ValueError
        address = ip_address(value)
    except ValueError:
        raise EgressDenied() from None
    if not rule.permits(address):
        raise EgressDenied()
    return address
