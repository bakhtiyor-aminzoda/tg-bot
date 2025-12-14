"""Reusable HTML and formatting helpers for the admin dashboard."""

from __future__ import annotations

import html
import textwrap
from datetime import datetime
from typing import Callable, Dict, List, Optional

_CHAT_TYPE_LABELS = {
    "private": "👤 Личные",
    "group": "👥 Группа",
    "supergroup": "👥 Супергруппа",
    "channel": "📣 Канал",
}


def format_chat_type_label(chat_type: Optional[str]) -> str:
    if not chat_type:
        return "—"
    return _CHAT_TYPE_LABELS.get(chat_type.lower(), "—")


def format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value} B"


def format_ratio(part: int, total: int) -> str:
    if total <= 0:
        return "0%"
    return f"{(part / total) * 100:.1f}%"


def format_duration(value: Optional[int]) -> str:
    if not value:
        return "—"
    seconds = int(value)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if minutes or not parts:
        parts.append(f"{minutes}м")
    return " ".join(parts)


def format_timestamp(ts: Optional[object]) -> str:
    if not ts:
        return "—"
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    text = str(ts)
    return text.replace("T", " ")


def format_since(seconds: Optional[float]) -> str:
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{int(seconds)} с назад"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} м назад"
    hours = int(minutes // 60)
    if hours < 24:
        return f"{hours} ч назад"
    days = int(hours // 24)
    return f"{days} д назад"


def render_select_options(options: Dict[str, str], current: str) -> str:
    return "".join(
        f"<option value=\"{html.escape(key)}\"{' selected' if key == current else ''}>{html.escape(label)}</option>"
        for key, label in options.items()
    )


def render_identity_badge(
    admin_identity_label: Optional[str], *, logout_link: Optional[str], multi_admin: bool
) -> str:
    if not admin_identity_label:
        return ""
    logout_button = (
        f"<a class=\"ghost-btn\" href=\"{logout_link}\">Выйти</a>" if (multi_admin and logout_link) else ""
    )
    extra = f" {logout_button}" if logout_button else ""
    return (
        "<div class=\"identity-badge\">Вошли как "
        f"<strong>{html.escape(str(admin_identity_label))}</strong>{extra}</div>"
    )


def render_summary_cards(
    *, total_downloads: int, successful: int, failed: int, total_bytes: int, unique_users: int
) -> str:
    return f"""
    <div class="cards">
        <article class="card">
            <p class="label">Всего загрузок</p>
            <p class="value">{total_downloads:,}</p>
        </article>
        <article class="card">
            <p class="label">Успешных</p>
            <p class="value">{successful:,}</p>
            <p class="hint">{format_ratio(successful, total_downloads)}</p>
        </article>
        <article class="card">
            <p class="label">Ошибок</p>
            <p class="value">{failed:,}</p>
            <p class="hint">{format_ratio(failed, total_downloads)}</p>
        </article>
        <article class="card">
            <p class="label">Данные</p>
            <p class="value">{format_bytes(int(total_bytes))}</p>
            <p class="hint">Пользователей: {unique_users}</p>
        </article>
    </div>
    """


def render_queue_section(runtime_state: Dict[str, object]) -> str:
    semaphore_state: Dict[str, object] = runtime_state.get("semaphore") or {}
    runtime_active_total = int(runtime_state.get("active_total", 0) or 0)
    runtime_pending_total = int(runtime_state.get("pending_total", 0) or 0)
    runtime_max_slots = int(semaphore_state.get("max_slots", 0) or 0)
    runtime_in_use = int(semaphore_state.get("in_use", 0) or 0)
    active_rows = runtime_state.get("active_rows") or []
    pending_rows = runtime_state.get("pending_rows") or []

    active_queue_rows = "".join(
        f"""
        <tr>
            <td>{row.get('user_id')}</td>
            <td>{row.get('active')}</td>
            <td class=\"{'danger-text' if row.get('is_stuck') else ''}\">{format_since(row.get('seconds_since_last'))}</td>
            <td>
                <button class=\"action-btn danger\" data-action=\"cancel_user\" data-user-id=\"{row.get('user_id')}\" data-confirm=\"Сбросить активные загрузки пользователя {row.get('user_id')}?\">Сбросить</button>
            </td>
        </tr>
        """
        for row in active_rows
    ) or "<tr><td colspan=\"4\">Нет активных загрузок</td></tr>"

    pending_queue_rows = "".join(
        f"""
        <tr>
            <td><code>{html.escape(str(row.get('token')))}</code></td>
            <td>{row.get('initiator_id') or '—'}</td>
            <td>{row.get('source_chat_id') or '—'}</td>
            <td>{format_since(row.get('age_seconds'))}</td>
            <td>
                <button class=\"action-btn danger\" data-action=\"drop_token\" data-token=\"{html.escape(str(row.get('token')))}\" data-confirm=\"Удалить pending кнопку?\">Удалить</button>
            </td>
        </tr>
        """
        for row in pending_rows
    ) or "<tr><td colspan=\"5\">Pending кнопок нет</td></tr>"

    queue_cards_html = f"""
    <div class=\"queue-grid\">
        <article class=\"card mini\">
            <p class=\"label\">Активных</p>
            <p class=\"value\">{runtime_active_total}</p>
        </article>
        <article class=\"card mini\">
            <p class=\"label\">Pending</p>
            <p class=\"value\">{runtime_pending_total}</p>
        </article>
        <article class=\"card mini\">
            <p class=\"label\">Слоты</p>
            <p class=\"value\">{runtime_in_use}/{runtime_max_slots}</p>
        </article>
    </div>
    """

    queue_actions_html = """
    <div class="queue-actions">
        <button type="button" class="action-btn" data-action="refresh">Обновить</button>
        <button type="button" class="action-btn danger" data-action="flush_tokens" data-confirm="Сбросить все pending кнопки?">Очистить pending</button>
    </div>
    """

    return f"""
    <section>
        <h2>Очередь и управление</h2>
        {queue_cards_html}
        {queue_actions_html}
        <div class=\"two-columns\">
            <div>
                <h3>Активные пользователи</h3>
                <table>
                    <thead>
                        <tr>
                            <th>Пользователь</th>
                            <th>Активность</th>
                            <th>Последняя активность</th>
                            <th>Действия</th>
                        </tr>
                    </thead>
                    <tbody>
                        {active_queue_rows}
                    </tbody>
                </table>
            </div>
            <div>
                <h3>Pending кнопки</h3>
                <table>
                    <thead>
                        <tr>
                            <th>Токен</th>
                            <th>Инициатор</th>
                            <th>Чат</th>
                            <th>Возраст</th>
                            <th>Действия</th>
                        </tr>
                    </thead>
                    <tbody>
                        {pending_queue_rows}
                    </tbody>
                </table>
            </div>
        </div>
    </section>
    """


def render_failures_section(failures: List[Dict[str, object]]) -> str:
    failure_rows = "".join(
        f"""
        <tr>
            <td>{html.escape(str(item.get('username') or item.get('user_id')))}</td>
            <td>{html.escape(str(item.get('platform', 'unknown')).upper())}</td>
            <td class=\"error\">{html.escape(str(item.get('error_message') or '—'))}</td>
            <td>{format_timestamp(item.get('timestamp'))}</td>
            <td>
                <span class=\"status-pill danger\">{html.escape(str(item.get('status')))}</span>
            </td>
        </tr>
        """
        for item in failures
    ) or "<tr><td colspan=\"5\">Ошибок нет</td></tr>"

    return f"""
    <section>
        <h2>Неудачные загрузки</h2>
        <table class=\"failure-table\">
            <thead>
                <tr>
                    <th>Пользователь</th>
                    <th>Платформа</th>
                    <th>Ошибка</th>
                    <th>Время</th>
                    <th>Статус</th>
                </tr>
            </thead>
            <tbody>
                {failure_rows}
            </tbody>
        </table>
    </section>
    """


def render_top_rows(top_users: List[Dict[str, object]]) -> str:
    return "".join(
        f"""
        <tr>
            <td>{idx + 1}</td>
            <td>{html.escape(str(user.get('username') or user.get('user_id')))}</td>
            <td>{user.get('total_downloads', 0)}</td>
            <td>{format_bytes(int(user.get('total_bytes', 0) or 0))}</td>
            <td>{user.get('failed_count', 0)}</td>
        </tr>
        """
        for idx, user in enumerate(top_users)
    ) or "<tr><td colspan=\"5\">Нет данных</td></tr>"


def render_platform_rows(platforms: List[Dict[str, object]]) -> str:
    return "".join(
        f"""
        <tr>
            <td>{html.escape(str(item.get('platform', 'unknown')).upper())}</td>
            <td>{item.get('download_count', 0)}</td>
            <td>{format_bytes(int(item.get('total_bytes', 0) or 0))}</td>
            <td>{item.get('failed_count', 0)}</td>
        </tr>
        """
        for item in platforms
    ) or "<tr><td colspan=\"4\">Нет данных</td></tr>"


def render_recent_rows(recent: List[Dict[str, object]]) -> str:
    return "".join(
        f"""
        <tr>
            <td>{html.escape(str(item.get('username') or item.get('user_id')))}</td>
            <td>{html.escape(str(item.get('platform', 'unknown')).upper())}</td>
            <td>{item.get('status')}</td>
            <td>{format_bytes(int(item.get('file_size_bytes') or 0))}</td>
            <td>{format_timestamp(item.get('timestamp'))}</td>
        </tr>
        """
        for item in recent
    ) or "<tr><td colspan=\"5\">История пуста</td></tr>"


def render_chat_table(
    *,
    chat_id: Optional[int],
    chat_list: List[Dict[str, object]],
    total_downloads: int,
    failed: int,
    unique_users: int,
    total_bytes: int,
    last_activity: Optional[object],
    build_link: Callable[[Dict[str, Optional[str]]], str],
) -> str:
    rows: List[str] = []
    global_link = build_link({"chat_id": None})
    rows.append(
        f"""
        <tr class=\"{'active' if chat_id is None else ''}\">
            <td><a href=\"{global_link}\">🌐 Вся история</a></td>
            <td>—</td>
            <td>—</td>
            <td>{total_downloads:,}</td>
            <td>{failed:,}</td>
            <td>{unique_users}</td>
            <td>{format_bytes(int(total_bytes))}</td>
            <td>{format_timestamp(last_activity)}</td>
        </tr>
        """
    )
    for chat in chat_list:
        cid = chat.get("chat_id")
        title = (str(chat.get("title") or "").strip()) or f"Чат #{cid}"
        if title.lower().startswith("chat #"):
            title = title.replace("Chat #", "Чат #", 1)
        row_link = build_link({"chat_id": cid})
        chat_type_label = format_chat_type_label(chat.get("chat_type"))
        rows.append(
            f"""
            <tr class=\"{'active' if cid == chat_id else ''}\">
                <td><a href=\"{row_link}\">{html.escape(str(title))}</a></td>
                <td>{cid}</td>
                <td>{chat_type_label}</td>
                <td>{chat.get('total_downloads', 0)}</td>
                <td>{chat.get('failed_downloads', 0)}</td>
                <td>{chat.get('unique_users', 0)}</td>
                <td>{format_bytes(int(chat.get('total_bytes', 0) or 0))}</td>
                <td>{format_timestamp(chat.get('last_activity'))}</td>
            </tr>
            """
        )
    return "".join(rows) or "<tr><td colspan=\"7\">Нет чатов</td></tr>"


def render_logs_list(error_logs: List[Dict[str, str]]) -> str:
    return "".join(
        f"""
        <li>
            <span class=\"log-ts\">{html.escape(log.get('timestamp', ''))}</span>
            <span class=\"log-level\">{html.escape(log.get('level', 'ERROR'))}</span>
            <span class=\"log-msg\">{html.escape(log.get('message', ''))}</span>
        </li>
        """
        for log in error_logs
    ) or "<li class=\"muted\">Последние ошибки не найдены</li>"


def _render_metrics_block(title_text: str, payload: Dict[str, object]) -> str:
    if not payload:
        return ""
    rows = "".join(
        f"<li><span>{html.escape(str(name))}</span><span>{value}</span></li>" for name, value in payload.items()
    )
    if not rows:
        return ""
    return (
        f"<div class=\"metrics-block\"><p class=\"metrics-title\">{html.escape(title_text)}</p><ul>{rows}</ul></div>"
    )


def render_health_section(
    health_info: Optional[Dict[str, object]], *, fallback_metrics: Dict[str, object], health_endpoint: str
) -> str:
    if not health_info:
        return f"<p class=\"muted\">Healthcheck отключён в конфиге ({html.escape(health_endpoint)}).</p>"

    health_status = str(health_info.get("status", "unknown"))
    status_class = ""
    normalized_status = health_status.lower()
    if normalized_status in ("warn", "warning"):
        status_class = "warning"
    elif normalized_status not in ("ok", "healthy"):
        status_class = "danger"

    uptime_text = format_duration(int(health_info.get("uptime_seconds") or 0))
    health_timestamp = "—"
    try:
        ts_value = float(health_info.get("timestamp"))
        iso = datetime.fromtimestamp(ts_value).isoformat(timespec="seconds")
        health_timestamp = format_timestamp(iso)
    except Exception:
        health_timestamp = "—"

    metrics = health_info.get("metrics") or {}
    counters = dict(metrics.get("counters", {}))
    gauges = dict(metrics.get("gauges", {}))
    metrics_html = "".join(
        block
        for block in (
            _render_metrics_block("Счётчики", counters),
            _render_metrics_block("Гейджи", gauges),
        )
        if block
    )
    if not metrics_html:
        metrics_html = _render_metrics_block("Базовые показатели", fallback_metrics)

    cookie_info = dict(health_info.get("instagram_cookies") or {})
    cookie_status = str(cookie_info.get("last_status", "disabled")) if cookie_info else "disabled"
    cookie_status_class = "danger" if cookie_status not in ("ok", "never", "skipped") else ""
    cookie_last = cookie_info.get("last_refresh_iso") or cookie_info.get("last_refresh_ts")
    if cookie_last and isinstance(cookie_last, (int, float)):
        try:
            cookie_last = format_timestamp(datetime.fromtimestamp(float(cookie_last)))
        except Exception:
            cookie_last = str(cookie_last)
    elif not cookie_last:
        cookie_last = "—"
    cookie_path = cookie_info.get("cookies_path")
    cookie_error = cookie_info.get("last_error") if cookie_info else None
    cookie_last_text = html.escape(str(cookie_last))

    video_cache_info = dict(health_info.get("video_cache") or {})
    vc_enabled = bool(video_cache_info.get("enabled")) if video_cache_info else False
    vc_hits = video_cache_info.get("hits") if video_cache_info else "—"
    vc_misses = video_cache_info.get("misses") if video_cache_info else "—"
    vc_last_store = (
        video_cache_info.get("last_store_iso")
        or video_cache_info.get("last_store_ts")
        or "—"
    )
    vc_dir = video_cache_info.get("dir") if video_cache_info else None

    health_endpoint_html = html.escape(health_endpoint)
    cookie_path_html = html.escape(str(cookie_path or "—"))
    cookie_error_html = html.escape(str(cookie_error or "—"))
    vc_dir_html = html.escape(str(vc_dir or "—"))
    vc_last_store_html = html.escape(str(vc_last_store))

    return (
        "<div class=\"health-grid\">"
        f"<div><p class=\"label\">Статус</p><span class=\"status-pill {status_class}\">{html.escape(health_status or 'disabled')}</span></div>"
        f"<div><p class=\"label\">Аптайм</p><p class=\"value\">{uptime_text}</p></div>"
        f"<div><p class=\"label\">Последнее обновление</p><p>{health_timestamp}</p></div>"
        f"<div><p class=\"label\">Endpoint</p><p>{health_endpoint_html}</p></div>"
        "</div>"
        f"<div class=\"health-grid\">{metrics_html}</div>"
        f"<div class=\"health-grid\">"
        f"<div><p class=\"label\">IG cookies</p><span class=\"status-pill {cookie_status_class}\">{html.escape(cookie_status)}</span></div>"
        f"<div><p class=\"label\">Файл</p><p>{cookie_path_html}</p></div>"
        f"<div><p class=\"label\">Последнее обновление</p><p>{cookie_last_text}</p></div>"
        f"<div><p class=\"label\">Ошибка</p><p>{cookie_error_html}</p></div>"
        "</div>"
        f"<div class=\"health-grid\">"
        f"<div><p class=\"label\">Video cache</p><span class=\"status-pill {'danger' if not vc_enabled else ''}\">{'on' if vc_enabled else 'off'}</span></div>"
        f"<div><p class=\"label\">🟢 hits</p><p>{vc_hits}</p></div>"
        f"<div><p class=\"label\">🔴 misses</p><p>{vc_misses}</p></div>"
        f"<div><p class=\"label\">Файл/dir</p><p>{vc_dir_html}</p></div>"
        f"<div><p class=\"label\">Последнее сохранение</p><p>{vc_last_store_html}</p></div>"
        "</div>"
    )


def render_dashboard_js() -> str:
    return textwrap.dedent(
        """
        (() => {
            const buttons = document.querySelectorAll('[data-action]');
            buttons.forEach((btn) => {
                btn.addEventListener('click', async (event) => {
                    const action = btn.dataset.action;
                    if (!action) {
                        return;
                    }
                    if (action === 'refresh') {
                        event.preventDefault();
                        window.location.reload();
                        return;
                    }
                    if (btn.dataset.confirm && !window.confirm(btn.dataset.confirm)) {
                        event.preventDefault();
                        return;
                    }
                    const payload = {};
                    if (btn.dataset.userId) {
                        payload.user_id = Number(btn.dataset.userId);
                    }
                    if (btn.dataset.token) {
                        payload.token = btn.dataset.token;
                    }
                    event.preventDefault();
                    try {
                        const response = await fetch(`/admin/api/actions/${action}`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            credentials: 'same-origin',
                            body: JSON.stringify(payload),
                        });
                        const body = await response.json().catch(() => ({}));
                        if (!response.ok || !body.ok) {
                            alert(body.error || 'Не удалось выполнить действие');
                            return;
                        }
                        window.location.reload();
                    } catch (err) {
                        console.error(err);
                        alert('Сетевая ошибка, попробуйте позже');
                    }
                });
            });
        })();
        """
    ).strip()


__all__ = [
    "format_chat_type_label",
    "format_bytes",
    "format_ratio",
    "format_duration",
    "format_timestamp",
    "format_since",
    "render_select_options",
    "render_identity_badge",
    "render_summary_cards",
    "render_queue_section",
    "render_failures_section",
    "render_top_rows",
    "render_platform_rows",
    "render_recent_rows",
    "render_chat_table",
    "render_logs_list",
    "render_health_section",
    "render_dashboard_js",
]
