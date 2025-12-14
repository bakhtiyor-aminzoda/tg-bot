"""Rendering helpers for quota-related UX flows."""
+
"""Rendering helpers for quota-related UX flows."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

from bot_app.ui.i18n import translate

UTC = timezone.utc


def _ensure_dt(value: Optional[object]) -> Optional[datetime]:
	if isinstance(value, datetime):
		return value if value.tzinfo else value.replace(tzinfo=UTC)
	if isinstance(value, str) and value:
		try:
			parsed = datetime.fromisoformat(value)
		except ValueError:
			return None
		return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
	return None


def _humanize_seconds(seconds: float, locale: str) -> str:
	total = max(0, int(seconds))
	minutes = total // 60 or 1
	hours, minutes = divmod(minutes, 60)
	days, hours = divmod(hours, 24)

	units_ru = [(days, "д"), (hours, "ч"), (minutes, "м")]
	units_en = [(days, "d"), (hours, "h"), (minutes, "m")]
	units = units_ru if locale == "ru" else units_en

	parts: list[str] = []
	for value, suffix in units:
		if value:
			parts.append(f"{value}{suffix}")
		if len(parts) == 2:
			break
	if not parts:
		parts.append("1m" if locale != "ru" else "1м")
	return " ".join(parts)


def _eta_phrase(plan: Dict[str, object], reason: str, locale: str) -> str:
	target = plan.get("next_reset", {}).get(reason)
	target_dt = _ensure_dt(target)
	if not target_dt:
		return ""
	now = datetime.now(tz=UTC)
	delta = (target_dt - now).total_seconds()
	return _humanize_seconds(delta, locale)


def quota_block_message(plan: Dict[str, object], locale: str) -> str:
	reason = plan.get("blocked_reason")
	if not reason:
		return ""
	limit = plan.get("limits", {}).get(reason) or 0
	eta = _eta_phrase(plan, reason, locale)
	template_key = "download.quota_daily_exceeded" if reason == "daily" else "download.quota_monthly_exceeded"
	body = translate(
		template_key,
		locale,
		plan=plan.get("plan_label", ""),
		limit=limit,
		reset=eta,
	)
	hint = translate("download.quota_upgrade_hint", locale)
	return f"{body}\n\n{hint}".strip()


def quota_summary(
	plan: Dict[str, object],
	locale: str,
	*,
	admin: bool = False,
	target_user_id: Optional[int] = None,
) -> str:
	limits = plan.get("limits", {})
	counters = plan.get("counters", {})
	remaining = plan.get("remaining", {})

	def _fmt_limit(limit: Optional[int]) -> str:
		if not limit:
			return "∞"
		return str(limit)

	def _fmt_remaining(key: str) -> str:
		value = remaining.get(key)
		if value is None:
			return "∞"
		return str(max(0, value))

	def _fmt_counter(key: str) -> str:
		return str(counters.get(key, 0))

	day_eta = _eta_phrase(plan, "daily", locale)
	month_eta = _eta_phrase(plan, "monthly", locale)

	if locale == "ru":
		header = f"📦 <b>Тариф: {plan.get('plan_label')}</b>"
		lines = [header]
		if admin and target_user_id is not None:
			lines.append(f"👤 User ID: <code>{target_user_id}</code>")
		lines.append(
			f"• День: {_fmt_counter('daily')} / {_fmt_limit(limits.get('daily'))} (осталось {_fmt_remaining('daily')})"
		)
		lines.append(
			f"• Месяц: {_fmt_counter('monthly')} / {_fmt_limit(limits.get('monthly'))} (осталось {_fmt_remaining('monthly')})"
		)
		lines.append(f"🔄 Обновление дня через {day_eta}")
		lines.append(f"📆 Обновление месяца через {month_eta}")
		return "\n".join(lines)

	header = f"📦 <b>Plan: {plan.get('plan_label')}</b>"
	lines = [header]
	if admin and target_user_id is not None:
		lines.append(f"👤 User ID: <code>{target_user_id}</code>")
	lines.append(
		f"• Daily: {_fmt_counter('daily')} / {_fmt_limit(limits.get('daily'))} (left {_fmt_remaining('daily')})"
	)
	lines.append(
		f"• Monthly: {_fmt_counter('monthly')} / {_fmt_limit(limits.get('monthly'))} (left {_fmt_remaining('monthly')})"
	)
	lines.append(f"🔄 Daily reset in {day_eta}")
	lines.append(f"📆 Monthly reset in {month_eta}")
	return "\n".join(lines)


__all__ = ["quota_block_message", "quota_summary"]
