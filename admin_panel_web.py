"""Лёгкий aiohttp-сервер для HTML-админки со статистикой."""

from __future__ import annotations

import asyncio
import html
import logging
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import quote_plus

from aiohttp import web

import config
from services import stats as stats_service
from monitoring import get_health_snapshot

CHAT_SORT_FIELDS = {"recent", "downloads", "data", "errors", "name"}
METRIC_SORT_FIELDS = {"downloads", "data", "errors", "name"}
CHAT_TYPE_LABELS = {
    "private": "👤 Личные",
    "group": "👥 Группа",
    "supergroup": "👥 Супергруппа",
    "channel": "📣 Канал",
}


def _format_chat_type_label(chat_type: Optional[str]) -> str:
    if not chat_type:
        return "—"
    return CHAT_TYPE_LABELS.get(chat_type.lower(), "—")


def _format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value} B"


def _format_ratio(part: int, total: int) -> str:
    if total <= 0:
        return "0%"
    return f"{(part / total) * 100:.1f}%"


def _format_duration(value: Optional[int]) -> str:
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


class AdminPanelServer:
    """Отдельный поток с aiohttp-приложением для просмотра статистики."""

    def __init__(self, host: str, port: int, access_token: Optional[str] = None) -> None:
        self._host = host
        self._port = port
        self._token = access_token
        self._runner: web.AppRunner | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown_event: asyncio.Event | None = None
        self._logger = logging.getLogger(__name__)
        self._log_tail = 50

    # ---------- Публичные методы ----------
    def ensure_running(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        def _run(loop: asyncio.AbstractEventLoop) -> None:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._run_app())

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=_run, args=(self._loop,), daemon=True)
        self._thread.start()
        self._logger.info("Admin panel server listening on %s:%s", self._host, self._port)

    def shutdown(self, timeout: float = 5.0) -> None:
        thread = self._thread
        if not thread:
            return

        if self._loop and self._shutdown_event:
            self._loop.call_soon_threadsafe(self._shutdown_event.set)

        thread.join(timeout=timeout)
        if thread.is_alive():
            self._logger.warning("Admin panel server thread did not stop within timeout")

        self._thread = None
        self._loop = None
        self._shutdown_event = None

    # ---------- aiohttp-приложение ----------
    async def _run_app(self) -> None:
        app = web.Application()
        app.router.add_get("/admin", self._handle_dashboard)
        app.router.add_get("/admin/api/dashboard", self._handle_dashboard_json)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host=self._host, port=self._port)
        await site.start()
        self._shutdown_event = asyncio.Event()
        try:
            await self._shutdown_event.wait()
        finally:
            await self._runner.cleanup()
            self._runner = None

    def _authorize(self, request: web.Request) -> bool:
        if not self._token:
            return True
        header_token = request.headers.get("X-Admin-Token")
        query_token = request.rel_url.query.get("token")
        return header_token == self._token or query_token == self._token

    def _unauthorized(self) -> web.Response:
        return web.Response(status=401, text="unauthorized", content_type="text/plain")

    def _parse_chat_id(self, request: web.Request) -> Optional[int]:
        value = request.rel_url.query.get("chat_id")
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def _collect_dashboard(
        self,
        chat_id: Optional[int],
        chat_sort: str,
        top_sort: str,
        platform_sort: str,
        search_query: Optional[str],
    ) -> Dict[str, object]:
        summary = stats_service.get_summary(chat_id)
        top_users = stats_service.get_top_users(chat_id, limit=10, order_by=top_sort)
        platforms = stats_service.get_platform_stats(chat_id, order_by=platform_sort)
        recent = stats_service.get_recent_downloads(chat_id, limit=20)
        chat_list = stats_service.list_chats(order_by=chat_sort, search=search_query, limit=100)
        scope = "Глобальная статистика" if chat_id is None else f"Чат #{chat_id}"
        health_data: Optional[Dict[str, object]] = None
        if getattr(config, "HEALTHCHECK_ENABLED", False):
            try:
                health_data = get_health_snapshot()
            except Exception:
                self._logger.debug("Не удалось получить health snapshot", exc_info=True)
        return {
            "summary": summary,
            "top_users": top_users,
            "platforms": platforms,
            "recent": recent,
            "scope": scope,
            "chat_id": chat_id,
            "chat_list": chat_list,
            "chat_sort": chat_sort,
            "top_sort": top_sort,
            "platform_sort": platform_sort,
            "search_query": search_query or "",
            "error_logs": self._read_error_logs(self._log_tail),
            "health": health_data,
        }

    def _resolve_sort(self, value: Optional[str], allowed: Set[str], default: str) -> str:
        if not value:
            return default
        return value if value in allowed else default

    async def _handle_dashboard(self, request: web.Request) -> web.Response:
        if not self._authorize(request):
            return self._unauthorized()

        query = request.rel_url.query
        chat_id = self._parse_chat_id(request)
        chat_sort = self._resolve_sort(query.get("chat_sort"), CHAT_SORT_FIELDS, "recent")
        top_sort = self._resolve_sort(query.get("top_sort"), METRIC_SORT_FIELDS, "downloads")
        platform_sort = self._resolve_sort(query.get("platform_sort"), METRIC_SORT_FIELDS, "downloads")

        search_query = query.get("search")
        if search_query:
            search_query = search_query.strip()
        if search_query == "":
            search_query = None

        dashboard = self._collect_dashboard(
            chat_id=chat_id,
            chat_sort=chat_sort,
            top_sort=top_sort,
            platform_sort=platform_sort,
            search_query=search_query,
        )
        token = query.get("token") if query.get("token") else None
        html_body = self._render_dashboard(dashboard, token)
        return web.Response(text=html_body, content_type="text/html")

    async def _handle_dashboard_json(self, request: web.Request) -> web.Response:
        if not self._authorize(request):
            return self._unauthorized()

        query = request.rel_url.query
        chat_id = self._parse_chat_id(request)
        chat_sort = self._resolve_sort(query.get("chat_sort"), CHAT_SORT_FIELDS, "recent")
        top_sort = self._resolve_sort(query.get("top_sort"), METRIC_SORT_FIELDS, "downloads")
        platform_sort = self._resolve_sort(query.get("platform_sort"), METRIC_SORT_FIELDS, "downloads")
        search_query = query.get("search")
        if search_query:
            search_query = search_query.strip() or None

        dashboard = self._collect_dashboard(
            chat_id=chat_id,
            chat_sort=chat_sort,
            top_sort=top_sort,
            platform_sort=platform_sort,
            search_query=search_query,
        )
        return web.json_response(dashboard)

    # ---------- HTML ----------
    def _render_dashboard(self, data: Dict[str, object], access_token: Optional[str]) -> str:
        summary: Dict[str, object] = data["summary"]  # type: ignore[assignment]
        top_users: List[Dict[str, object]] = data["top_users"]  # type: ignore[assignment]
        platforms: List[Dict[str, object]] = data["platforms"]  # type: ignore[assignment]
        recent: List[Dict[str, object]] = data["recent"]  # type: ignore[assignment]
        chat_list: List[Dict[str, object]] = data.get("chat_list", [])  # type: ignore[assignment]
        scope: str = str(data["scope"])
        chat_id = data.get("chat_id")
        chat_sort = str(data.get("chat_sort", "recent"))
        top_sort = str(data.get("top_sort", "downloads"))
        platform_sort = str(data.get("platform_sort", "downloads"))
        search_query = str(data.get("search_query") or "")
        error_logs: List[Dict[str, str]] = data.get("error_logs", [])  # type: ignore[assignment]
        health_info: Optional[Dict[str, object]] = data.get("health")  # type: ignore[assignment]

        total_downloads = summary.get("total_downloads", 0)
        successful = summary.get("successful_downloads", 0)
        failed = summary.get("failed_downloads", 0)
        total_bytes = summary.get("total_bytes", 0)
        unique_users = summary.get("unique_users", 0)
        last_activity = summary.get("last_activity")
        health_status = None
        health_timestamp = None
        uptime_text = "—"
        counters: Dict[str, object] = {}
        gauges: Dict[str, object] = {}
        health_endpoint = f"{getattr(config, 'HEALTHCHECK_HOST', '0.0.0.0')}:{getattr(config, 'HEALTHCHECK_PORT', 8080)}"
        if health_info:
            health_status = str(health_info.get("status", "unknown"))
            uptime_text = _format_duration(int(health_info.get("uptime_seconds") or 0))
            try:
                ts = float(health_info.get("timestamp"))
                health_timestamp = _format_timestamp(datetime.fromtimestamp(ts).isoformat(timespec="seconds"))
            except Exception:
                health_timestamp = "—"
            metrics = health_info.get("metrics") or {}
            counters = dict(metrics.get("counters", {}))  # type: ignore[arg-type]
            gauges = dict(metrics.get("gauges", {}))  # type: ignore[arg-type]

        def render_options(options: Dict[str, str], current: str) -> str:
            return "".join(
                f"<option value=\"{html.escape(key)}\"{' selected' if key == current else ''}>{html.escape(label)}</option>"
                for key, label in options.items()
            )

        def build_query(overrides: Dict[str, Optional[str]]) -> str:
            base = {
                "chat_id": str(chat_id) if chat_id is not None else None,
                "chat_sort": chat_sort,
                "top_sort": top_sort,
                "platform_sort": platform_sort,
                "search": search_query or None,
            }
            base.update({k: (None if v in (None, "") else str(v)) for k, v in overrides.items()})
            parts = []
            for key, value in base.items():
                if value is None:
                    continue
                parts.append(f"{key}={quote_plus(value)}")
            if access_token:
                parts.append(f"token={quote_plus(access_token)}")
            return "&".join(parts)

        def build_link(overrides: Dict[str, Optional[str]]) -> str:
            query = build_query(overrides)
            return f"/admin?{query}" if query else "/admin"

        chat_sort_options = {
            "recent": "По активности",
            "downloads": "По загрузкам",
            "data": "По объёму",
            "errors": "По ошибкам",
            "name": "По названию",
        }
        metric_sort_options = {
            "downloads": "По загрузкам",
            "data": "По объёму",
            "errors": "По ошибкам",
            "name": "По имени",
        }

        cards_html = f"""
        <div class=\"cards\">
            <article class=\"card\">
                <p class=\"label\">Всего загрузок</p>
                <p class=\"value\">{total_downloads:,}</p>
            </article>
            <article class=\"card\">
                <p class=\"label\">Успешных</p>
                <p class=\"value\">{successful:,}</p>
                <p class=\"hint\">{_format_ratio(successful, total_downloads)}</p>
            </article>
            <article class=\"card\">
                <p class=\"label\">Ошибок</p>
                <p class=\"value\">{failed:,}</p>
                <p class=\"hint\">{_format_ratio(failed, total_downloads)}</p>
            </article>
            <article class=\"card\">
                <p class=\"label\">Данные</p>
                <p class=\"value\">{_format_bytes(int(total_bytes))}</p>
                <p class=\"hint\">Пользователей: {unique_users}</p>
            </article>
        </div>
        """

        top_rows = "".join(
            f"""
            <tr>
                <td>{idx + 1}</td>
                <td>{html.escape(str(user.get('username') or user.get('user_id')))}</td>
                <td>{user.get('total_downloads', 0)}</td>
                <td>{_format_bytes(int(user.get('total_bytes', 0) or 0))}</td>
                <td>{user.get('failed_count', 0)}</td>
            </tr>
            """
            for idx, user in enumerate(top_users)
        ) or "<tr><td colspan=\"5\">Нет данных</td></tr>"

        platform_rows = "".join(
            f"""
            <tr>
                <td>{html.escape(str(item.get('platform', 'unknown')).upper())}</td>
                <td>{item.get('download_count', 0)}</td>
                <td>{_format_bytes(int(item.get('total_bytes', 0) or 0))}</td>
                <td>{item.get('failed_count', 0)}</td>
            </tr>
            """
            for item in platforms
        ) or "<tr><td colspan=\"4\">Нет данных</td></tr>"

        recent_rows = "".join(
            f"""
            <tr>
                <td>{html.escape(str(item.get('username') or item.get('user_id')))}</td>
                <td>{html.escape(str(item.get('platform', 'unknown')).upper())}</td>
                <td>{item.get('status')}</td>
                <td>{_format_bytes(int(item.get('file_size_bytes') or 0))}</td>
                <td>{_format_timestamp(item.get('timestamp'))}</td>
            </tr>
            """
            for item in recent
        ) or "<tr><td colspan=\"5\">История пуста</td></tr>"

        chat_rows: List[str] = []
        global_link = build_link({"chat_id": None})
        chat_rows.append(
            f"""
            <tr class=\"{'active' if chat_id is None else ''}\">
                <td><a href=\"{global_link}\">🌐 Вся история</a></td>
                <td>—</td>
                <td>—</td>
                <td>{total_downloads:,}</td>
                <td>{failed:,}</td>
                <td>{unique_users}</td>
                <td>{_format_bytes(int(total_bytes))}</td>
                <td>{_format_timestamp(last_activity)}</td>
            </tr>
            """
        )
        for chat in chat_list:
            cid = chat.get("chat_id")
            title = (str(chat.get("title") or "").strip()) or f"Чат #{cid}"
            if title.lower().startswith("chat #"):
                title = title.replace("Chat #", "Чат #", 1)
            row_link = build_link({"chat_id": cid})
            chat_type_label = _format_chat_type_label(chat.get("chat_type"))
            chat_rows.append(
                f"""
                <tr class=\"{'active' if cid == chat_id else ''}\">
                    <td><a href=\"{row_link}\">{html.escape(str(title))}</a></td>
                    <td>{cid}</td>
                    <td>{chat_type_label}</td>
                    <td>{chat.get('total_downloads', 0)}</td>
                    <td>{chat.get('failed_downloads', 0)}</td>
                    <td>{chat.get('unique_users', 0)}</td>
                    <td>{_format_bytes(int(chat.get('total_bytes', 0) or 0))}</td>
                    <td>{_format_timestamp(chat.get('last_activity'))}</td>
                </tr>
                """
            )

        chat_table = "".join(chat_rows) or "<tr><td colspan=\"7\">Нет чатов</td></tr>"

        logs_html = "".join(
            f"""
            <li>
                <span class=\"log-ts\">{html.escape(log.get('timestamp', ''))}</span>
                <span class=\"log-level\">{html.escape(log.get('level', 'ERROR'))}</span>
                <span class=\"log-msg\">{html.escape(log.get('message', ''))}</span>
            </li>
            """
            for log in error_logs
        ) or "<li class=\"muted\">Последние ошибки не найдены</li>"

        def render_metrics_block(title_text: str, payload: Dict[str, object]) -> str:
            if not payload:
                return ""
            rows = "".join(
                f"<li><span>{html.escape(str(name))}</span><span>{value}</span></li>"
                for name, value in payload.items()
            )
            if not rows:
                return ""
            return f"<div class=\"metrics-block\"><p class=\"metrics-title\">{html.escape(title_text)}</p><ul>{rows}</ul></div>"

        fallback_metrics = {
            "Всего загрузок": f"{total_downloads:,}",
            "Успешных": f"{successful:,}",
            "Ошибок": f"{failed:,}",
            "Уникальных пользователей": unique_users,
            "Чатов в базе": len(chat_list),
            "Объём данных": _format_bytes(int(total_bytes)),
        }

        metrics_parts = [
            block
            for block in (
                render_metrics_block("Счётчики", counters),
                render_metrics_block("Гейджи", gauges),
            )
            if block
        ]
        if not metrics_parts:
            metrics_parts.append(render_metrics_block("Базовые показатели", fallback_metrics))
        metrics_html = "".join(metrics_parts)

        status_class = "danger" if health_status not in ("ok", "healthy", None) else ""
        if health_info:
            health_html = (
                "<div class=\"health-grid\">"
                f"<div><p class=\"label\">Статус</p><span class=\"status-pill {status_class}\">{html.escape(health_status or 'disabled')}</span></div>"
                f"<div><p class=\"label\">Аптайм</p><p class=\"value\">{uptime_text}</p></div>"
                f"<div><p class=\"label\">Последнее обновление</p><p>{health_timestamp or '—'}</p></div>"
                f"<div><p class=\"label\">Endpoint</p><p>{html.escape(health_endpoint)}</p></div>"
                "</div>"
                f"<div class=\"health-grid\">{metrics_html}</div>"
            )
        else:
            health_html = f"<p class=\"muted\">Healthcheck отключён в конфиге ({html.escape(health_endpoint)}).</p>"

        chat_value = html.escape(str(chat_id)) if chat_id is not None else ""
        search_value = html.escape(search_query)
        token_input = (
            f"<input type=\"hidden\" name=\"token\" value=\"{html.escape(access_token)}\" />"
            if access_token
            else ""
        )
        chat_sort_options_html = render_options(chat_sort_options, chat_sort)
        top_sort_options_html = render_options(metric_sort_options, top_sort)
        platform_sort_options_html = render_options(metric_sort_options, platform_sort)

        return f"""
        <!DOCTYPE html>
        <html lang=\"ru\">
        <head>
            <meta charset=\"utf-8\" />
            <title>Admin Panel — Media Bandit</title>
            <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
            <style>
                :root {{
                    --bg: #050915;
                    --surface: rgba(13,23,42,0.85);
                    --surface-alt: rgba(15,27,52,0.6);
                    --accent: #58f29c;
                    --accent-secondary: #4cc9f0;
                    --text: #f5f7ff;
                    --muted: #94a3b8;
                    --danger: #f87171;
                    font-family: 'Space Grotesk', 'Fira Sans', sans-serif;
                }}
                * {{ box-sizing: border-box; margin: 0; padding: 0; }}
                body {{
                    min-height: 100vh;
                    background: radial-gradient(circle at top, #112044, #050915);
                    color: var(--text);
                    padding: 32px;
                    display: flex;
                    justify-content: center;
                }}
                main {{
                    width: min(1200px, 100%);
                    display: flex;
                    flex-direction: column;
                    gap: 24px;
                }}
                header {{
                    display: flex;
                    flex-direction: column;
                    gap: 16px;
                }}
                .title-row {{
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    flex-wrap: wrap;
                    gap: 12px;
                }}
                h1 {{ font-size: 28px; letter-spacing: 0.5px; }}
                .scope-chip {{
                    background: rgba(255,255,255,0.08);
                    padding: 6px 14px;
                    border-radius: 32px;
                    font-size: 14px;
                    letter-spacing: 0.5px;
                }}
                .cards {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 16px;
                }}
                .card {{
                    background: var(--surface);
                    border: 1px solid rgba(255,255,255,0.05);
                    border-radius: 16px;
                    padding: 18px;
                    box-shadow: 0 20px 60px rgba(0,0,0,0.35);
                }}
                .label {{
                    font-size: 14px;
                    color: var(--muted);
                    text-transform: uppercase;
                    letter-spacing: 1px;
                    margin-bottom: 6px;
                }}
                .value {{
                    font-size: clamp(28px, 5vw, 36px);
                    font-weight: 600;
                }}
                .hint {{
                    margin-top: 6px;
                    color: var(--muted);
                    font-size: 13px;
                }}
                .controls {{
                    background: var(--surface);
                    border: 1px solid rgba(255,255,255,0.05);
                    border-radius: 16px;
                    padding: 16px;
                    display: flex;
                    gap: 12px;
                    flex-wrap: wrap;
                    align-items: flex-end;
                }}
                .control-group {{
                    display: flex;
                    flex-direction: column;
                    gap: 6px;
                    min-width: 180px;
                }}
                .control-group label {{
                    font-size: 11px;
                    text-transform: uppercase;
                    color: var(--muted);
                    letter-spacing: 0.8px;
                }}
                input[type="number"], input[type="text"], select {{
                    background: var(--surface-alt);
                    border: 1px solid rgba(255,255,255,0.15);
                    border-radius: 8px;
                    color: var(--text);
                    padding: 8px 12px;
                }}
                select {{ min-width: 140px; }}
                button {{
                    background: var(--accent);
                    color: #04161c;
                    border: none;
                    border-radius: 8px;
                    padding: 10px 18px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: transform 0.15s ease;
                }}
                button:hover {{ transform: translateY(-1px); }}
                .ghost-btn {{
                    border: 1px solid rgba(255,255,255,0.25);
                    border-radius: 8px;
                    padding: 10px 16px;
                    text-decoration: none;
                    color: var(--text);
                }}
                .ghost-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
                section {{
                    background: var(--surface-alt);
                    border-radius: 18px;
                    border: 1px solid rgba(255,255,255,0.05);
                    padding: 20px;
                    box-shadow: inset 0 1px 0 rgba(255,255,255,0.05);
                }}
                section h2 {{
                    font-size: 18px;
                    margin-bottom: 14px;
                    letter-spacing: 0.5px;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    font-size: 14px;
                }}
                th, td {{
                    padding: 10px;
                    text-align: left;
                    border-bottom: 1px solid rgba(255,255,255,0.06);
                }}
                th {{ color: var(--muted); font-weight: 500; }}
                tbody tr:hover {{ background: rgba(255,255,255,0.03); }}
                .chat-table tr.active {{ background: rgba(88,242,156,0.1); }}
                .chat-table td:first-child a {{ color: var(--text); text-decoration: none; font-weight: 600; }}
                .two-columns {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                    gap: 16px;
                }}
                .logs-list {{
                    list-style: none;
                    display: flex;
                    flex-direction: column;
                    gap: 8px;
                    max-height: 260px;
                    overflow-y: auto;
                }}
                .logs-list li {{
                    padding: 10px 12px;
                    background: var(--surface);
                    border-radius: 12px;
                    border: 1px solid rgba(255,255,255,0.05);
                }}
                .log-ts {{
                    font-family: 'Fira Code', monospace;
                    font-size: 12px;
                    color: var(--muted);
                    margin-right: 8px;
                }}
                .log-level {{
                    font-weight: 600;
                    color: var(--danger);
                    margin-right: 8px;
                }}
                .log-msg {{ color: var(--text); }}
                .muted {{ color: var(--muted); }}
                .health-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
                    gap: 16px;
                    margin-top: 8px;
                }}
                .status-pill {{
                    display: inline-flex;
                    align-items: center;
                    gap: 8px;
                    padding: 6px 12px;
                    border-radius: 999px;
                    font-weight: 600;
                    background: rgba(88,242,156,0.15);
                }}
                .status-pill.danger {{ background: rgba(248,113,113,0.2); color: #fecaca; }}
                .metrics-block {{
                    background: rgba(0,0,0,0.2);
                    border-radius: 12px;
                    padding: 12px;
                    border: 1px solid rgba(255,255,255,0.05);
                }}
                .metrics-block ul {{
                    list-style: none;
                    display: flex;
                    flex-direction: column;
                    gap: 6px;
                }}
                .metrics-block li {{
                    display: flex;
                    justify-content: space-between;
                    font-family: 'Fira Code', monospace;
                    font-size: 13px;
                }}
                .metrics-title {{
                    font-size: 13px;
                    text-transform: uppercase;
                    color: var(--muted);
                    letter-spacing: 0.6px;
                    margin-bottom: 8px;
                }}
                @media (max-width: 720px) {{
                    body {{ padding: 16px; }}
                    .controls {{ flex-direction: column; align-items: stretch; }}
                    .control-group {{ width: 100%; }}
                }}
            </style>
        </head>
        <body>
            <main>
                <header>
                    <div class=\"title-row\">
                        <h1>Media Bandit · Админ-панель</h1>
                        <span class=\"scope-chip\">{html.escape(scope)}</span>
                    </div>
                    <form method=\"get\" action=\"/admin\" class=\"controls\">
                        <div class=\"control-group\">
                            <label>ID чата</label>
                            <input type=\"number\" name=\"chat_id\" placeholder=\"Например 12345\" value=\"{chat_value}\" />
                        </div>
                        <div class=\"control-group\">
                            <label>Поиск по названию</label>
                            <input type=\"text\" name=\"search\" placeholder=\"Название чата\" value=\"{search_value}\" />
                        </div>
                        <div class=\"control-group\">
                            <label>Сортировка чатов</label>
                            <select name=\"chat_sort\">
                                {chat_sort_options_html}
                            </select>
                        </div>
                        <div class=\"control-group\">
                            <label>Топ пользователей</label>
                            <select name=\"top_sort\">
                                {top_sort_options_html}
                            </select>
                        </div>
                        <div class=\"control-group\">
                            <label>Платформы</label>
                            <select name=\"platform_sort\">
                                {platform_sort_options_html}
                            </select>
                        </div>
                        {token_input}
                        <button type=\"submit\">Применить</button>
                        <a class=\"ghost-btn\" href=\"{build_link({'chat_id': None, 'search': None})}\">Сбросить фильтр</a>
                    </form>
                </header>
                {cards_html}
                <section>
                    <h2>Чаты</h2>
                    <table class=\"chat-table\">
                        <thead>
                            <tr>
                                <th>Чат</th>
                                <th>ID</th>
                                <th>Тип</th>
                                <th>Загрузок</th>
                                <th>Ошибок</th>
                                <th>Пользователей</th>
                                <th>Объём</th>
                                <th>Активность</th>
                            </tr>
                        </thead>
                        <tbody>
                            {chat_table}
                        </tbody>
                    </table>
                </section>
                <div class=\"two-columns\">
                    <section>
                        <h2>Топ пользователей</h2>
                        <table>
                            <thead>
                                <tr>
                                    <th>#</th>
                                    <th>Пользователь</th>
                                    <th>Загрузок</th>
                                    <th>Объём</th>
                                    <th>Ошибки</th>
                                </tr>
                            </thead>
                            <tbody>
                                {top_rows}
                            </tbody>
                        </table>
                    </section>
                    <section>
                        <h2>Платформы</h2>
                        <table>
                            <thead>
                                <tr>
                                    <th>Платформа</th>
                                    <th>Загрузок</th>
                                    <th>Объём</th>
                                    <th>Ошибки</th>
                                </tr>
                            </thead>
                            <tbody>
                                {platform_rows}
                            </tbody>
                        </table>
                    </section>
                </div>
                <section>
                    <h2>Последние загрузки</h2>
                    <table>
                        <thead>
                            <tr>
                                <th>Пользователь</th>
                                <th>Платформа</th>
                                <th>Статус</th>
                                <th>Объём</th>
                                <th>Время</th>
                            </tr>
                        </thead>
                        <tbody>
                            {recent_rows}
                        </tbody>
                    </table>
                </section>
                <section>
                    <h2>Healthcheck</h2>
                    {health_html}
                </section>
                <section>
                    <h2>Ошибки</h2>
                    <ul class=\"logs-list\">
                        {logs_html}
                    </ul>
                </section>
            </main>
        </body>
        </html>
        """

    def _read_error_logs(self, max_lines: int) -> List[Dict[str, str]]:
        log_path = getattr(config, "LOG_FILE", None)
        if not log_path:
            return []
        path = Path(log_path)
        if not path.exists():
            return []
        errors = deque(maxlen=max_lines)
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    if " | ERROR | " in line or " | CRITICAL | " in line:
                        errors.append(line.strip())
        except Exception as exc:
            self._logger.debug("Не удалось прочитать лог: %s", exc)
            return []

        parsed: List[Dict[str, str]] = []
        for entry in reversed(errors):
            parts = [part.strip() for part in entry.split("|", 3)]
            if len(parts) >= 4:
                ts, level, logger_name, message = parts[:4]
            else:
                ts, level, logger_name, message = "", "ERROR", "", entry
            parsed.append(
                {
                    "timestamp": ts,
                    "level": level,
                    "logger": logger_name,
                    "message": message,
                }
            )
        return parsed


def _format_timestamp(ts: Optional[str]) -> str:
    if not ts:
        return "—"
    return ts.replace("T", " ")