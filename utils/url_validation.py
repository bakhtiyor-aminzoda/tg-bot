from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    """Raised when a URL looks unsafe for server-side fetching."""


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_FORBIDDEN_SUFFIXES = (".local", ".localhost", ".internal")


def ensure_safe_public_url(url: str) -> str:
    """Validate URL scheme/host to minimize SSRF vectors."""
    if not url:
        raise UnsafeURLError("Пустая ссылка.")
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeURLError("Поддерживаются только http/https ссылки.")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("Не удалось определить хост в ссылке.")

    lowered = host.lower()
    if lowered in _LOCAL_HOSTS or any(lowered.endswith(sfx) for sfx in _FORBIDDEN_SUFFIXES):
        raise UnsafeURLError("Ссылка указывает на локальный ресурс и заблокирована.")

    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        ip = None

    if ip and (ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local or ip.is_multicast):
        raise UnsafeURLError("Ссылка указывает на внутренний адрес и заблокирована.")

    return url
