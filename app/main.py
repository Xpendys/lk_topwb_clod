"""
Точка входа FastAPI.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, mailer, stats, webhook
from .config import settings
from .db import db_cursor, init_db

app = FastAPI(title="Топай в ТОП · Реферальная программа")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)

app.include_router(webhook.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def render(request: Request, template: str, **ctx) -> HTMLResponse:
    ctx.setdefault("user", auth.current_user(request))
    return templates.TemplateResponse(request, template, ctx)


def require_login(request: Request):
    user = auth.current_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303), None
    return None, user


def require_admin(request: Request):
    if not auth.current_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    return None


# ---------- public ----------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return render(request, "index.html")


@app.get("/main-test", response_class=HTMLResponse)
def main_test(request: Request):
    return render(request, "main_test.html")


@app.get("/register", response_class=HTMLResponse)
def register_get(request: Request):
    return render(request, "register.html", form={})


@app.post("/register", response_class=HTMLResponse)
def register_post(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    platform: str = Form(...),
):
    form = {"first_name": first_name, "last_name": last_name, "email": email, "platform": platform}
    try:
        user_id = auth.register_user(email, password, first_name, last_name, platform)
    except auth.AuthError as e:
        return render(request, "register.html", form=form, error=str(e))
    token = auth.create_email_confirmation_token(user_id)
    confirmation_url = f"{settings.LK_BASE_URL}/confirm-email?token={token}"
    user = auth.get_user_by_id(user_id)
    send_error = ""
    try:
        sent = mailer.send_email_confirmation(user["email"], user["first_name"], confirmation_url)
    except Exception as exc:
        logger.exception("Failed to send confirmation email to %s", user["email"])
        sent = False
        send_error = str(exc)
    return render(request, "check_email.html", email=email.strip().lower(), sent=sent, send_error=send_error)


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return render(request, "login.html", form={})


@app.post("/login", response_class=HTMLResponse)
def login_post(request: Request, email: str = Form(...), password: str = Form(...)):
    try:
        user_id = auth.authenticate(email, password)
    except auth.EmailNotConfirmed as e:
        return render(request, "login.html", form={"email": email}, error=str(e))
    if user_id is None:
        return render(request, "login.html", form={"email": email}, error="Неверный email или пароль")
    response = RedirectResponse("/lk", status_code=303)
    response.set_cookie(auth.SESSION_COOKIE, auth.make_session_cookie(user_id),
                        max_age=60*60*24*30, httponly=True, samesite="lax")
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(auth.SESSION_COOKIE)
    return response


@app.get("/confirm-email", response_class=HTMLResponse)
def confirm_email(request: Request, token: str = ""):
    confirmed = bool(token) and auth.confirm_email_token(token)
    return render(request, "email_confirmed.html", confirmed=confirmed)


@app.post("/resend-confirmation", response_class=HTMLResponse)
def resend_confirmation(request: Request, email: str = Form(...)):
    user = auth.get_user_by_email(email)
    if user is None:
        return render(request, "check_email.html", email=email, sent=True)
    if user["email_confirmed"]:
        return RedirectResponse("/login", status_code=303)

    token = auth.create_email_confirmation_token(user["id"])
    confirmation_url = f"{settings.LK_BASE_URL}/confirm-email?token={token}"
    send_error = ""
    try:
        sent = mailer.send_email_confirmation(user["email"], user["first_name"], confirmation_url)
    except Exception as exc:
        logger.exception("Failed to resend confirmation email to %s", user["email"])
        sent = False
        send_error = str(exc)
    return render(request, "check_email.html", email=user["email"], sent=sent, resent=True, send_error=send_error)


# ---------- личный кабинет ----------

@app.get("/lk", response_class=HTMLResponse)
def lk(request: Request):
    redirect, user = require_login(request)
    if redirect:
        return redirect
    user_stats = stats.get_user_stats(user["id"])
    referrals = stats.get_user_referrals(user["id"])
    commissions = stats.get_user_commissions(user["id"])
    ref_link = f"{settings.PUBLIC_SITE_URL}/?ref={user['ref_code']}"
    return render(request, "lk.html", stats=user_stats, referrals=referrals,
                  commissions=commissions, ref_link=ref_link,
                  commission_percent=settings.COMMISSION_PERCENT)


@app.get("/lk/requisites", response_class=HTMLResponse)
def requisites_get(request: Request):
    redirect, user = require_login(request)
    if redirect:
        return redirect
    with db_cursor() as cur:
        cur.execute("SELECT requisites_phone, requisites_name, requisites_bank FROM users WHERE id=?", (user["id"],))
        row = cur.fetchone()
        req = dict(row) if row else {}
    return render(request, "lk_requisites.html", req=req)


@app.post("/lk/requisites", response_class=HTMLResponse)
def requisites_post(
    request: Request,
    requisites_phone: str = Form(...),
    requisites_name: str = Form(...),
    requisites_bank: str = Form(""),
):
    redirect, user = require_login(request)
    if redirect:
        return redirect
    with db_cursor() as cur:
        cur.execute("UPDATE users SET requisites_phone=?, requisites_name=?, requisites_bank=? WHERE id=?",
                    (requisites_phone, requisites_name, requisites_bank, user["id"]))
    with db_cursor() as cur:
        cur.execute("SELECT requisites_phone, requisites_name, requisites_bank FROM users WHERE id=?", (user["id"],))
        req = dict(cur.fetchone())
    return render(request, "lk_requisites.html", req=req, message="Реквизиты сохранены!")


# ---------- админ ----------

@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_get(request: Request):
    if auth.current_admin(request):
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(request, "admin_login.html", {"user": None, "form": {}})


@app.post("/admin/login", response_class=HTMLResponse)
def admin_login_post(request: Request, login: str = Form(...), password: str = Form(...)):
    if not auth.admin_credentials_valid(login, password):
        return templates.TemplateResponse(
            request,
            "admin_login.html",
            {"user": None, "form": {"login": login}, "error": "Неверный логин или пароль"},
        )
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(
        auth.ADMIN_SESSION_COOKIE,
        auth.make_admin_session_cookie(),
        max_age=60*60*24*30,
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/admin/logout")
def admin_logout():
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(auth.ADMIN_SESSION_COOKIE)
    return response


@app.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request):
    redirect = require_admin(request)
    if redirect:
        return redirect
    users = stats.get_all_users_admin()
    return templates.TemplateResponse(
        request,
        "admin.html",
        {"users": users, "user": None, "message": request.query_params.get("msg", "")},
    )



@app.post("/admin/payout")
def admin_payout(request: Request, user_id: int = Form(...), amount: int = Form(...)):
    redirect = require_admin(request)
    if redirect:
        return redirect
    with db_cursor() as cur:
        cur.execute("INSERT INTO payouts (user_id, amount, note) VALUES (?, ?, ?)",
                    (user_id, amount, "Выплата через админ-панель"))
    from fastapi.responses import RedirectResponse as RR
    return RR("/admin?msg=Выплата+записана", status_code=303)


# ---------- health ----------

@app.get("/healthz")
def healthz():
    return {"status": "ok"}
