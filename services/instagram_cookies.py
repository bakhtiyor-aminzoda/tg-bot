"""Automatic Instagram cookie refresher using Playwright."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Dict, Iterable, Optional

import config

try:  # Playwright is optional — feature disabled if missing
	from playwright.async_api import (  # type: ignore
		TimeoutError as PlaywrightTimeoutError,
		async_playwright,
	)
except Exception:  # pragma: no cover - fallback when playwright is absent
	async_playwright = None  # type: ignore
	PlaywrightTimeoutError = Exception  # type: ignore

logger = logging.getLogger(__name__)

REFRESH_ERROR_MARKERS = (
	"Requested content is not available",
	"login required",
	"rate-limit",
)

DESKTOP_UA = (
	"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
	"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class RefreshResult:
	status: str
	message: str = ""
	refreshed: bool = False


class NeedTwoFactorCode(Exception):
	"""Raised when Instagram blocks login behind 2FA without available codes."""


class InstagramCookieRefresher:
	"""Encapsulates Playwright login flow and cookie serialization."""

	def __init__(self) -> None:
		self._lock = asyncio.Lock()
		self._last_refresh_ts: float = 0.0
		self._last_status: str = "never"
		self._last_error: Optional[str] = None
		self._cookies_path = Path(config.IG_COOKIES_PATH) if config.IG_COOKIES_PATH else None
		self._backup_codes: Deque[str] = deque(config.IG_2FA_BACKUP_CODES)

	def _has_credentials(self) -> bool:
		return bool(config.IG_LOGIN and config.IG_PASSWORD and self._cookies_path)

	@property
	def enabled(self) -> bool:
		return bool(config.IG_COOKIES_AUTO_REFRESH and self._has_credentials())

	@property
	def refresh_interval_seconds(self) -> float:
		return float(config.IG_COOKIES_REFRESH_INTERVAL_HOURS) * 3600.0

	def should_refresh(self) -> bool:
		if not self._has_credentials() or not self._cookies_path:
			return False
		if not self._cookies_path.exists():
			return True
		age_hours = (time.time() - self._cookies_path.stat().st_mtime) / 3600.0
		return age_hours >= config.IG_COOKIES_REFRESH_INTERVAL_HOURS

	async def refresh(
		self,
		*,
		force: bool = False,
		reason: Optional[str] = None,
		allow_disabled: bool = False,
	) -> RefreshResult:
		if not self._has_credentials():
			return RefreshResult(status="disabled", message="Instagram credentials are missing")
		if not allow_disabled and not self.enabled:
			return RefreshResult(status="disabled", message="Auto-refresh disabled")
		if async_playwright is None:
			logger.warning("Playwright is not installed; Instagram auto-refresh unavailable")
			return RefreshResult(status="error", message="playwright missing")

		async with self._lock:
			if not force and not self.should_refresh():
				return RefreshResult(status="skipped", message="Cookies still fresh")
			logger.info("Refreshing Instagram cookies (reason=%s)...", reason or "scheduled")
			try:
				await self._login_and_dump_cookies()
			except NeedTwoFactorCode as err:
				self._last_status = "needs-2fa"
				self._last_error = str(err)
				logger.warning("Instagram requested 2FA; no backup codes provided")
				return RefreshResult(status="needs-2fa", message=str(err))
			except Exception as err:  # pragma: no cover - network dependent
				self._last_status = "error"
				self._last_error = str(err)
				logger.exception("Failed to refresh Instagram cookies")
				return RefreshResult(status="error", message=str(err))

			self._last_status = "ok"
			self._last_error = None
			self._last_refresh_ts = time.time()
			logger.info("Instagram cookies refreshed: %s", self._cookies_path)
			return RefreshResult(status="ok", refreshed=True)

	async def _login_and_dump_cookies(self) -> None:
		assert async_playwright is not None  # already checked upstream
		if not self._cookies_path:
			raise RuntimeError("IG_COOKIES_PATH is not configured")

		async with async_playwright() as pw:
			browser = await pw.chromium.launch(
				headless=True,
				args=["--disable-blink-features=AutomationControlled", "--disable-features=IsolateOrigins,site-per-process"],
			)
			context = await browser.new_context(
				locale="en-US",
				viewport={"width": 1280, "height": 720},
				timezone_id="UTC",
				user_agent=DESKTOP_UA,
			)
			await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
			page = await context.new_page()
			page.set_default_timeout(40000)
			try:
				await page.goto("https://www.instagram.com/accounts/login/", wait_until="networkidle", timeout=30000)
				await self._ensure_login_form(page)
				await page.fill('input[name="username"]', str(config.IG_LOGIN))
				await page.fill('input[name="password"]', str(config.IG_PASSWORD))
				await page.click('button[type="submit"]')
				await self._handle_two_factor_if_needed(page)
				await self._wait_for_home(page)
				await self._dismiss_post_login_modals(page)
				cookies = await context.cookies()
				self._write_netscape_cookies(cookies)
			finally:
				await context.close()
				await browser.close()

	async def _handle_two_factor_if_needed(self, page) -> None:
		# Instagram может открыть страницу challenge. Пытаемся найти поле ввода кода.
		await page.wait_for_timeout(2000)
		selectors = [
			'input[name="verificationCode"]',
			'input[name="security_code"]',
		]
		for selector in selectors:
			if await self._has_selector(page, selector):
				code = self._get_backup_code()
				if not code:
					raise NeedTwoFactorCode("Instagram запросил 2FA, добавьте IG_2FA_BACKUP_CODES")
					await page.fill(selector, code)
					await page.click('button[type="submit"]')
					return

	async def _wait_for_home(self, page) -> None:
		try:
			await page.wait_for_url(
				lambda url: url.startswith("https://www.instagram.com/") and "login" not in url and "challenge" not in url,
				timeout=40000,
			)
		except PlaywrightTimeoutError as err:
			raise RuntimeError("Не удалось дождаться загрузки главной страницы Instagram") from err

	async def _dismiss_post_login_modals(self, page) -> None:
		for text in ("Not now", "Не сейчас", "Save info"):
			try:
				await page.get_by_text(text, exact=True).click(timeout=2000)
			except Exception:
				continue

	async def _ensure_login_form(self, page) -> None:
		deadline = time.time() + 60  # seconds
		input_selectors = [
			'input[name="username"]',
			'input[aria-label="Phone number, username, or email"]',
			'input[name="emailOrPhone"]',
			'input[name="usernameOrEmail"]',
		]
		trigger_selectors = [
			"button:has-text('Log in')",
			"button:has-text('Log In')",
			"button:has-text('Войти')",
			"a:has-text('Log in')",
			"text=Log in",
		]
		attempt = 0
		while time.time() < deadline:
			for selector in input_selectors:
				if await self._has_selector(page, selector):
					return
			await self._maybe_accept_cookie_banner(page)
			attempt += 1
			clicked = False
			for trigger in trigger_selectors:
				try:
					locator = page.locator(trigger).first
					if await locator.count() and await locator.is_visible():
						await locator.click(timeout=1500)
						clicked = True
						break
				except Exception:
					continue
			if clicked:
				await page.wait_for_timeout(1200)
				continue
			if attempt % 4 == 0:
				try:
					await page.goto(
						"https://www.instagram.com/accounts/login/?source=auth_switcher",
						wait_until="domcontentloaded",
						timeout=20000,
					)
				except Exception:
					pass
			await page.wait_for_timeout(700)
		html_snippet = (await page.content())[:4000]
		logger.error("Instagram login form not found (url=%s)", page.url)
		logger.debug("Instagram login HTML snippet: %s", html_snippet)
		raise RuntimeError("Не удалось отобразить форму входа Instagram")

	async def _maybe_accept_cookie_banner(self, page) -> None:
		selectors = [
			"button:has-text('Allow essential and optional cookies')",
			"button:has-text('Allow all cookies')",
			"button:has-text('Разрешить все cookie')",
			"button:has-text('Разрешить все файлы cookie')",
			"button:has-text('Only allow essential cookies')",
			"button:has-text('Allow essential cookies')",
			"button:has-text('Allow Cookies')",
			"button:has-text('Accept all')",
			"button:has-text('Accept All')",
			"button:has-text('Принять все')",
		]
		for selector in selectors:
			try:
				await page.locator(selector).click(timeout=2000)
				logger.info("Instagram cookie banner accepted via selector %s", selector)
				return
			except Exception:
				continue

	async def _has_selector(self, page, selector: str) -> bool:
		try:
			await page.wait_for_selector(selector, timeout=1000)
			return True
		except Exception:
			return False

	def _get_backup_code(self) -> Optional[str]:
		if not self._backup_codes:
			return None
		code = self._backup_codes.popleft()
		logger.info("Используем резервный 2FA-код Instagram (%s остаётся)", len(self._backup_codes))
		return code

	def _write_netscape_cookies(self, cookies: Iterable[Dict]) -> None:
		assert self._cookies_path is not None
		lines = ["# Netscape HTTP Cookie File"]
		for cookie in cookies:
			domain = cookie.get("domain", "")
			include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
			path = cookie.get("path", "/") or "/"
			secure = "TRUE" if cookie.get("secure") else "FALSE"
			expires_raw = cookie.get("expires")
			if expires_raw:
				expiry = str(int(expires_raw))
			else:
				expiry = str(int(time.time()) + 365 * 24 * 3600)
			name = cookie.get("name", "")
			value = cookie.get("value", "")
			lines.append("\t".join([domain, include_subdomains, path, secure, expiry, name, value]))

		self._cookies_path.parent.mkdir(parents=True, exist_ok=True)
		self._cookies_path.write_text("\n".join(lines), encoding="utf-8")

	def state(self) -> Dict[str, Optional[float | str]]:
		return {
			"enabled": self.enabled,
			"has_credentials": self._has_credentials(),
			"last_status": self._last_status,
			"last_error": self._last_error,
			"last_refresh_ts": self._last_refresh_ts,
			"cookies_path": str(self._cookies_path) if self._cookies_path else None,
		}

	def should_retry_for_error(self, error_text: str) -> bool:
		return bool(
			self._has_credentials()
			and error_text
			and any(marker.lower() in error_text.lower() for marker in REFRESH_ERROR_MARKERS)
		)


_refresher = InstagramCookieRefresher()


async def refresh_instagram_cookies(
	*,
	force: bool = False,
	reason: Optional[str] = None,
	allow_disabled: bool = False,
) -> RefreshResult:
	"""Public wrapper for forcing cookie refresh."""
	return await _refresher.refresh(force=force, reason=reason, allow_disabled=allow_disabled)


def is_enabled() -> bool:
	return _refresher.enabled


def should_refresh() -> bool:
	return _refresher.should_refresh()


def refresh_interval_seconds() -> float:
	return _refresher.refresh_interval_seconds


def get_state() -> Dict[str, Optional[float | str]]:
	return _refresher.state()


def should_retry_for_error(error_text: str) -> bool:
	return _refresher.should_retry_for_error(error_text)


__all__ = [
	"refresh_instagram_cookies",
	"should_refresh",
	"should_retry_for_error",
	"refresh_interval_seconds",
	"get_state",
	"is_enabled",
	"RefreshResult",
]
