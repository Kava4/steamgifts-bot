from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from web.app_state import state
from version import APP_VERSION

WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

SESSION_COOKIE = "sgb_session"
WEBUI_PASSWORD = os.environ.get("WEBUI_PASSWORD", "").strip()


def _password_configured() -> bool:
    return bool(WEBUI_PASSWORD)


def _session_value() -> str:
    digest = hmac.new(
        WEBUI_PASSWORD.encode("utf-8"),
        state.session_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def _is_authenticated(request: Request) -> bool:
    if not _password_configured():
        return True
    return request.cookies.get(SESSION_COOKIE) == _session_value()


def require_auth(request: Request) -> None:
    if not _is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")


class CookiePayload(BaseModel):
    cookie: str = ""
    indiegala_cookie: str = ""


class SettingsPayload(BaseModel):
    manual_select_giveaways: Optional[bool] = None
    refresh_delay_minutes: Optional[int] = None
    max_pages: Optional[int] = None
    max_giveaway_end_hours: Optional[int] = None
    enable_indiegala_beta: Optional[bool] = None
    indiegala_entry_delay: Optional[int] = None
    indiegala_min_cost: Optional[int] = None
    notify_on_win: Optional[bool] = None


class ManualPayload(BaseModel):
    enter: bool


class RemovePayload(BaseModel):
    xsrf_token: str = Field(min_length=1)


class LoginPayload(BaseModel):
    password: str = ""


class IndieGalaTestPayload(BaseModel):
    cookie: str = ""


def create_app() -> FastAPI:
    app = FastAPI(title="SteamGifts Bot", version=APP_VERSION)

    @app.on_event("startup")
    async def _startup() -> None:
        import asyncio

        state.bind_loop(asyncio.get_running_loop())

    app.mount(
        "/static",
        StaticFiles(directory=str(WEB_DIR / "static")),
        name="static",
    )

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> Response:
        if not _password_configured():
            return RedirectResponse("/", status_code=302)
        if _is_authenticated(request):
            return RedirectResponse("/", status_code=302)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "", "version": APP_VERSION},
        )

    @app.post("/login")
    async def login_submit(request: Request) -> Response:
        if not _password_configured():
            return RedirectResponse("/", status_code=302)

        form = await request.form()
        password = str(form.get("password", ""))
        if not hmac.compare_digest(password, WEBUI_PASSWORD):
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "error": "Invalid password",
                    "version": APP_VERSION,
                },
                status_code=401,
            )

        response = RedirectResponse("/", status_code=302)
        response.set_cookie(
            SESSION_COOKIE,
            _session_value(),
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 30,
        )
        return response

    @app.post("/logout")
    async def logout() -> Response:
        response = RedirectResponse("/login", status_code=302)
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> Response:
        if not _is_authenticated(request):
            return RedirectResponse("/login", status_code=302)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "version": APP_VERSION,
                "auth_enabled": _password_configured(),
            },
        )

    @app.get("/api/state")
    async def api_state(_: None = Depends(require_auth)) -> dict[str, Any]:
        return state.snapshot()

    @app.get("/api/settings")
    async def get_settings(_: None = Depends(require_auth)) -> dict[str, Any]:
        return state.get_web_settings()

    @app.post("/api/settings")
    async def post_settings(
        payload: SettingsPayload, _: None = Depends(require_auth)
    ) -> dict[str, Any]:
        data = payload.model_dump(exclude_none=True)
        return state.update_settings(data)

    @app.get("/api/cookies")
    async def get_cookies(_: None = Depends(require_auth)) -> dict[str, Any]:
        return {
            "cookie": state.read_cookie(),
            "indiegala_cookie": state.read_indiegala_cookie(),
        }

    @app.post("/api/cookies")
    async def post_cookies(
        payload: CookiePayload, _: None = Depends(require_auth)
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        try:
            if payload.cookie.strip():
                result["cookie"] = state.save_cookie(payload.cookie)
            if payload.indiegala_cookie.strip():
                result["indiegala_cookie"] = state.save_indiegala_cookie(
                    payload.indiegala_cookie
                )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if not result:
            raise HTTPException(status_code=400, detail="Nothing to save")
        return result

    @app.post("/api/bot/start")
    async def bot_start(_: None = Depends(require_auth)) -> dict[str, Any]:
        try:
            state.start_bot()
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"running": True}

    @app.post("/api/bot/stop")
    async def bot_stop(_: None = Depends(require_auth)) -> dict[str, Any]:
        state.stop_bot()
        return {"running": False}

    @app.post("/api/points")
    async def fetch_points(_: None = Depends(require_auth)) -> dict[str, Any]:
        try:
            return state.fetch_points()
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=500, detail=str(error)) from error

    @app.post("/api/indiegala/test")
    async def test_indiegala(
        payload: IndieGalaTestPayload, _: None = Depends(require_auth)
    ) -> dict[str, Any]:
        try:
            return state.test_indiegala(payload.cookie or None)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=500, detail=str(error)) from error

    @app.get("/api/entered")
    async def get_entered(_: None = Depends(require_auth)) -> list[dict[str, Any]]:
        try:
            return state.list_entered()
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=500, detail=str(error)) from error

    @app.post("/api/entered/{code}/remove")
    async def remove_entered(
        code: str, payload: RemovePayload, _: None = Depends(require_auth)
    ) -> dict[str, Any]:
        try:
            state.remove_entered(code, payload.xsrf_token)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=500, detail=str(error)) from error
        return {"ok": True, "code": code}

    @app.get("/api/wins")
    async def get_wins(_: None = Depends(require_auth)) -> list[dict[str, Any]]:
        return state.list_wins()

    @app.post("/api/manual")
    async def manual_decision(
        payload: ManualPayload, _: None = Depends(require_auth)
    ) -> dict[str, Any]:
        state.submit_manual(payload.enter)
        return {"ok": True}

    @app.post("/api/logs/clear")
    async def clear_logs(_: None = Depends(require_auth)) -> dict[str, Any]:
        state.clear_logs()
        return {"ok": True}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        if _password_configured():
            cookie = websocket.cookies.get(SESSION_COOKIE)
            if cookie != _session_value():
                await websocket.close(code=4401)
                return

        await websocket.accept()
        queue = state.subscribe()
        try:
            await websocket.send_json(state.snapshot())
            while True:
                event = await queue.get()
                await websocket.send_json(event)
        except WebSocketDisconnect:
            pass
        finally:
            state.unsubscribe(queue)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> Response:
        if (
            exc.status_code == 401
            and request.url.path.startswith("/api/")
        ):
            return JSONResponse({"detail": exc.detail}, status_code=401)
        if exc.status_code == 401 and not request.url.path.startswith("/api/"):
            return RedirectResponse("/login", status_code=302)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return app


app = create_app()
