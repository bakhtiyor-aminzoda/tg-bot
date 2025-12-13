import unittest

from utils.url_validation import ensure_safe_public_url, UnsafeURLError


class UrlValidationTests(unittest.TestCase):
    def test_allows_https_public_url(self):
        self.assertEqual(ensure_safe_public_url("https://example.com/video"), "https://example.com/video")

    def test_rejects_non_http_scheme(self):
        with self.assertRaises(UnsafeURLError):
            ensure_safe_public_url("ftp://example.com/file")

    def test_rejects_loopback_ip(self):
        with self.assertRaises(UnsafeURLError):
            ensure_safe_public_url("http://127.0.0.1/resource")

    def test_rejects_ipv6_loopback(self):
        with self.assertRaises(UnsafeURLError):
            ensure_safe_public_url("http://[::1]/path")


if __name__ == "__main__":
    unittest.main()
