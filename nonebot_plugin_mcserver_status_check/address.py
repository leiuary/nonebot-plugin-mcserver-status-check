"""Validate Minecraft server address syntax without making network requests."""

import re
from ipaddress import ip_address


def is_valid_server_address(address: str) -> bool:
    if not address or any(character.isspace() for character in address):
        return False

    host = address
    port = None
    bracketed = address.startswith("[")
    if bracketed:
        match = re.fullmatch(r"\[([^\[\]]+)\](?::([0-9]{1,5}))?", address)
        if match is None:
            return False
        host, port = match.groups()
    elif address.count(":") == 1:
        host, port = address.rsplit(":", 1)

    if port is not None and (
        re.fullmatch(r"[0-9]{1,5}", port) is None or not 1 <= int(port) <= 65535
    ):
        return False

    if "%" in host:
        return False
    try:
        parsed_ip = ip_address(host)
        return not bracketed or parsed_ip.version == 6
    except ValueError:
        if bracketed:
            return False

    try:
        hostname = host.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    if hostname.endswith("."):
        hostname = hostname[:-1]
    labels = hostname.split(".")
    return (
        len(hostname) <= 253
        and len(labels) >= 2
        and not labels[-1].isdigit()
        and all(
            re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
            for label in labels
        )
    )
