from __future__ import annotations

import unittest

from repository.certificate import (
    hostname_matches,
    normalize_hostname,
    parse_sans,
    select_hostname,
)


class CertificateHostnameTestCase(unittest.TestCase):
    def test_dns_and_ipv4_sans_are_kept_distinct(self) -> None:
        dns_names, addresses = parse_sans(
            "X509v3 Subject Alternative Name:\n"
            "    DNS:packages.example.com, IP Address:192.0.2.10, "
            "IP Address:2001:db8::1\n"
        )
        self.assertEqual(dns_names, ("packages.example.com",))
        self.assertEqual(addresses, ("192.0.2.10",))

    def test_one_dns_name_is_selected_even_with_ip_sans(self) -> None:
        self.assertEqual(
            select_hostname(("packages.example.com",), None), "packages.example.com"
        )

    def test_multiple_dns_names_require_selection(self) -> None:
        with self.assertRaisesRegex(ValueError, "multiple DNS SANs"):
            select_hostname(("one.example.com", "two.example.com"), None)

    def test_requested_dns_name_must_be_covered(self) -> None:
        with self.assertRaisesRegex(ValueError, "not covered"):
            select_hostname(("packages.example.com",), "other.example.com")

    def test_hostname_must_be_a_safe_fqdn(self) -> None:
        for hostname in ("localhost", "bad_name.example.com", "-bad.example.com"):
            with (
                self.subTest(hostname=hostname),
                self.assertRaisesRegex(ValueError, "invalid fully qualified"),
            ):
                normalize_hostname(hostname)

    def test_wildcard_matches_exactly_one_label(self) -> None:
        self.assertTrue(hostname_matches("*.example.com", "packages.example.com"))
        self.assertFalse(hostname_matches("*.example.com", "deep.packages.example.com"))
        self.assertEqual(
            select_hostname(("*.example.com",), "packages.example.com"),
            "packages.example.com",
        )


if __name__ == "__main__":
    unittest.main()
