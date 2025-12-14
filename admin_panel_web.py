"""Лёгкий aiohttp-сервер для HTML-админки со статистикой."""

from __future__ import annotations

import asyncio
import html
import logging
import threading
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote_plus

from aiohttp import web
from jinja2 import Environment, FileSystemLoader, select_autoescape

import config
from admin_panel import (
    AdminAuthManager,
    AdminIdentity,
    AuthResult,
    DashboardDataProvider,
    RuntimeController,
)
from admin_panel import admin_panel_ui as admin_ui

CHAT_SORT_FIELDS = {"recent", "downloads", "data", "errors", "name"}
METRIC_SORT_FIELDS = {"downloads", "data", "errors", "name"}


class AdminPanelServer:
    """Отдельный поток с aiohttp-приложением для просмотра статистики."""

    def __init__(
        self,
        host: str,
        port: int,
        access_token: Optional[str] = None,
        admin_accounts: Optional[Dict[str, Dict[str, str]]] = None,
        cookie_secret: Optional[str] = None,
        session_ttl: int = 6 * 60 * 60,
        bot_loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        self._host = host
        self._port = port
        self._runner: web.AppRunner | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown_event: asyncio.Event | None = None
        self._logger = logging.getLogger(__name__)
        self._log_tail = 50
        self._auth = AdminAuthManager(
            access_token=access_token,
            admin_accounts=admin_accounts,
            cookie_secret=cookie_secret,
            session_ttl=session_ttl,
        )
        self._runtime = RuntimeController(bot_loop=bot_loop, logger=self._logger)
        self._data_provider = DashboardDataProvider(
            runtime_controller=self._runtime,
            log_reader=self._read_error_logs,
            logger=self._logger,
        )
        template_dir = Path(__file__).with_name("admin_panel") / "templates"
        self._template_env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self._dashboard_template = self._template_env.get_template("dashboard.html")

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
        app.router.add_post("/admin/api/actions/{action}", self._handle_action)
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

    def _unauthorized(self) -> web.Response:
        if self._auth.multi_admin_enabled():
            body = """
            <!DOCTYPE html>
            <html><head><title>Admin login</title></head>
            <body style="font-family: sans-serif; padding: 2rem;">
                <h2>Admin authentication required</h2>
                <p>Укажите свой персональный токен в параметре <code>?token=...</code>
                или добавьте заголовок <code>X-Admin-Token</code>.</p>
            </body></html>
            """
            return web.Response(status=401, text=body, content_type="text/html")
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
        admin_identity: Optional[AdminIdentity],
    ) -> Dict[str, object]:
        data = self._data_provider.collect_dashboard(
            chat_id=chat_id,
            chat_sort=chat_sort,
            top_sort=top_sort,
            platform_sort=platform_sort,
            search_query=search_query,
            log_tail=self._log_tail,
        )
        data["admin_identity"] = admin_identity.display if admin_identity else None
        data["multi_admin"] = self._auth.multi_admin_enabled()
        return data

    def _resolve_sort(self, value: Optional[str], allowed: Set[str], default: str) -> str:
        if not value:
            return default
        return value if value in allowed else default

    async def _handle_dashboard(self, request: web.Request) -> web.Response:
        query = request.rel_url.query
        if self._auth.multi_admin_enabled() and query.get("logout") == "1":
            return self._auth.logout_response()

        auth = self._auth.authorize(request)
        if not auth.ok:
            return self._unauthorized()
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
            admin_identity=auth.identity,
        )
        token_param = query.get("token") if (query.get("token") and not self._auth.multi_admin_enabled()) else None
        html_body = self._render_dashboard(dashboard, token_param)
        response = web.Response(text=html_body, content_type="text/html")
        self._auth.attach_cookies(response, auth)
        return response

    async def _handle_dashboard_json(self, request: web.Request) -> web.Response:
        query = request.rel_url.query
        auth = self._auth.authorize(request)
        if not auth.ok:
            return self._unauthorized()
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
            admin_identity=auth.identity,
        )
        response = web.json_response(dashboard)
        self._auth.attach_cookies(response, auth)
        return response

    async def _handle_action(self, request: web.Request) -> web.Response:
        auth = self._auth.authorize(request)
        if not auth.ok:
            return self._unauthorized()
        action = request.match_info.get("action", "")
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        try:
            result = self._runtime.perform_action(action, payload)
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception:
            self._logger.exception("Admin action %s failed", action)
            return web.json_response({"ok": False, "error": "internal error"}, status=500)
        response = web.json_response({"ok": True, **result})
        self._auth.attach_cookies(response, auth)
        return response

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
        runtime_state: Dict[str, object] = data.get("runtime", {})  # type: ignore[assignment]
        failures: List[Dict[str, object]] = data.get("failures", [])  # type: ignore[assignment]
        alerts: List[Dict[str, object]] = data.get("alerts", [])  # type: ignore[assignment]
        admin_identity_label = data.get("admin_identity")
        multi_admin = bool(data.get("multi_admin"))

        total_downloads = int(summary.get("total_downloads", 0) or 0)
        successful = int(summary.get("successful_downloads", 0) or 0)
        failed = int(summary.get("failed_downloads", 0) or 0)
        total_bytes = int(summary.get("total_bytes", 0) or 0)
        unique_users = int(summary.get("unique_users", 0) or 0)
        last_activity = summary.get("last_activity")
        health_endpoint = f"{getattr(config, 'HEALTHCHECK_HOST', '0.0.0.0')}:{getattr(config, 'HEALTHCHECK_PORT', 8080)}"

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

        logout_link = build_link({"logout": "1"})
        identity_html = admin_ui.render_identity_badge(
            admin_identity_label,
            logout_link=logout_link,
            multi_admin=multi_admin,
        )

        cards_html = admin_ui.render_summary_cards(
            total_downloads=total_downloads,
            successful=successful,
            failed=failed,
            total_bytes=total_bytes,
            unique_users=unique_users,
        )

        queue_section_html = admin_ui.render_queue_section(runtime_state)
        failures_section_html = admin_ui.render_failures_section(failures)
        top_rows = admin_ui.render_top_rows(top_users)
        platform_rows = admin_ui.render_platform_rows(platforms)
        recent_rows = admin_ui.render_recent_rows(recent)
        chat_table = admin_ui.render_chat_table(
            chat_id=chat_id,
            chat_list=chat_list,
            total_downloads=total_downloads,
            failed=failed,
            unique_users=unique_users,
            total_bytes=total_bytes,
            last_activity=last_activity,
            build_link=build_link,
        )
        logs_html = admin_ui.render_logs_list(error_logs)
        alerts_html = admin_ui.render_alerts_section(alerts)

        fallback_metrics = {
            "Всего загрузок": f"{total_downloads:,}",
            "Успешных": f"{successful:,}",
            "Ошибок": f"{failed:,}",
            "Уникальных пользователей": unique_users,
            "Чатов в базе": len(chat_list),
            "Объём данных": admin_ui.format_bytes(total_bytes),
        }
        health_html = admin_ui.render_health_section(
            health_info=health_info,
            fallback_metrics=fallback_metrics,
            health_endpoint=health_endpoint,
        )

        chat_value = str(chat_id) if chat_id is not None else ""
        search_value = search_query
        token_input = (
            f"<input type=\"hidden\" name=\"token\" value=\"{html.escape(access_token)}\" />"
            if (access_token and not multi_admin)
            else ""
        )
        chat_sort_options_html = admin_ui.render_select_options(chat_sort_options, chat_sort)
        top_sort_options_html = admin_ui.render_select_options(metric_sort_options, top_sort)
        platform_sort_options_html = admin_ui.render_select_options(metric_sort_options, platform_sort)
        dashboard_js = admin_ui.render_dashboard_js()

        reset_link = build_link({"chat_id": None, "search": None})
        context = {
            "scope": scope,
            "identity_html": identity_html,
            "chat_value": chat_value,
            "search_value": search_value,
            "chat_sort_options_html": chat_sort_options_html,
            "top_sort_options_html": top_sort_options_html,
            "platform_sort_options_html": platform_sort_options_html,
            "token_input": token_input,
            "reset_link": reset_link,
            "cards_html": cards_html,
            "queue_section_html": queue_section_html,
            "chat_table": chat_table,
            "top_rows": top_rows,
            "platform_rows": platform_rows,
            "recent_rows": recent_rows,
            "failures_section_html": failures_section_html,
            "health_html": health_html,
            "alerts_html": alerts_html,
            "logs_html": logs_html,
            "dashboard_js": dashboard_js,
        }
        return self._dashboard_template.render(**context)

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