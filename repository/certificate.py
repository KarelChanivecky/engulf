#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ipaddress
import re
import ssl
import subprocess
import sys
import time
from pathlib import Path

DNS_PATTERN = re.compile(r"(?:^|[,\s])DNS:([^,\s]+)", re.IGNORECASE)
IP_PATTERN = re.compile(r"IP Address:([^,\s]+)", re.IGNORECASE)
HOSTNAME_PATTERN = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)


def _openssl(*arguments: str, input_data: bytes | None = None) -> bytes:
    try:
        input_arguments = (
            {"input": input_data}
            if input_data is not None
            else {"stdin": subprocess.DEVNULL}
        )
        completed = subprocess.run(
            ("openssl", *arguments),
            capture_output=True,
            check=False,
            **input_arguments,
        )
    except FileNotFoundError as error:
        raise ValueError("OpenSSL is required") from error
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise ValueError(detail or f"OpenSSL exited with {completed.returncode}")
    return completed.stdout


def parse_sans(output: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    dns_names = tuple(
        dict.fromkeys(match.group(1) for match in DNS_PATTERN.finditer(output))
    )
    addresses: list[str] = []
    for match in IP_PATTERN.finditer(output):
        address = ipaddress.ip_address(match.group(1))
        if address.version == 4:
            addresses.append(str(address))
    return dns_names, tuple(dict.fromkeys(addresses))


def certificate_sans(certificate: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    output = _openssl(
        "x509", "-in", str(certificate), "-noout", "-ext", "subjectAltName"
    ).decode("utf-8", "replace")
    return parse_sans(output)


def hostname_matches(pattern: str, hostname: str) -> bool:
    pattern = pattern.rstrip(".").lower()
    hostname = hostname.rstrip(".").lower()
    if "*" not in pattern:
        return pattern == hostname
    if not pattern.startswith("*.") or pattern.count("*") != 1:
        return False
    suffix = pattern[2:]
    labels = hostname.split(".")
    return len(labels) == len(suffix.split(".")) + 1 and hostname.endswith(f".{suffix}")


def normalize_hostname(hostname: str) -> str:
    hostname = hostname.rstrip(".").lower()
    if not HOSTNAME_PATTERN.fullmatch(hostname):
        raise ValueError(f"invalid fully qualified hostname: {hostname!r}")
    return hostname


def select_hostname(dns_names: tuple[str, ...], requested: str | None) -> str:
    if requested:
        requested = normalize_hostname(requested)
        if not any(hostname_matches(name, requested) for name in dns_names):
            raise ValueError(
                f"requested hostname {requested!r} is not covered by a DNS SAN"
            )
        return requested
    concrete = tuple(name.rstrip(".").lower() for name in dns_names if "*" not in name)
    if len(concrete) == 1:
        return normalize_hostname(concrete[0])
    if not concrete:
        raise ValueError("certificate has no concrete DNS SAN; pass --hostname")
    raise ValueError("certificate has multiple DNS SANs; pass --hostname")


def validate_certificate(certificate: Path, key: Path) -> None:
    if not certificate.is_file():
        raise ValueError(f"certificate does not exist: {certificate}")
    if not key.is_file():
        raise ValueError(f"private key does not exist: {key}")
    validity = _openssl(
        "x509", "-in", str(certificate), "-noout", "-startdate", "-enddate"
    ).decode("ascii", "strict")
    validity_fields = dict(line.split("=", 1) for line in validity.splitlines())
    current_time = time.time()
    if current_time < ssl.cert_time_to_seconds(validity_fields["notBefore"]):
        raise ValueError("certificate is not valid yet")
    if current_time > ssl.cert_time_to_seconds(validity_fields["notAfter"]):
        raise ValueError("certificate has expired")
    certificate_key = _openssl("x509", "-in", str(certificate), "-pubkey", "-noout")
    private_key = _openssl("pkey", "-in", str(key), "-pubout")
    if certificate_key.strip() != private_key.strip():
        raise ValueError("certificate and private key do not match")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cert", required=True, type=Path)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--hostname")
    parser.add_argument("--field", choices=("hostname", "ipv4"), required=True)
    arguments = parser.parse_args()
    try:
        validate_certificate(arguments.cert, arguments.key)
        dns_names, addresses = certificate_sans(arguments.cert)
        hostname = select_hostname(dns_names, arguments.hostname)
    except ValueError as error:
        parser.error(str(error))
    if arguments.field == "hostname":
        print(hostname)
    else:
        print("\n".join(addresses))
    return 0


if __name__ == "__main__":
    sys.exit(main())
