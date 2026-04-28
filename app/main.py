"""
Точка входа FastAPI.
"""
from __future__ import annotations

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, stats, webhook
from .config import settings
from .db import db_cursor, init_db

app = FastAPI(title="Топай в ТОП · Реферальная программа")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

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


# ---------- public ----------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return render(request, "index.html")


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
    response = RedirectResponse("/lk", status_code=303)
    response.set_cookie(auth.SESSION_COOKIE, auth.make_session_cookie(user_id),
                        max_age=60*60*24*30, httponly=True, samesite="lax")
    return response


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return render(request, "login.html", form={})


@app.post("/login", response_class=HTMLResponse)
def login_post(request: Request, email: str = Form(...), password: str = Form(...)):
    user_id = auth.authenticate(email, password)
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

@app.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request, key: str = ""):
    if key != settings.ALBATO_WEBHOOK_SECRET:
        return HTMLResponse("<h1>403 Forbidden</h1>", status_code=403)
    users = stats.get_all_users_admin()
    return templates.TemplateResponse(request, "admin.html", {"users": users, "user": None, "admin_key": key, "message": request.query_params.get("msg", "")})



@app.post("/admin/payout")
def admin_payout(request: Request, key: str = "", user_id: int = Form(...), amount: int = Form(...)):
    if key != settings.ALBATO_WEBHOOK_SECRET:
        return HTMLResponse("<h1>403 Forbidden</h1>", status_code=403)
    with db_cursor() as cur:
        cur.execute("INSERT INTO payouts (user_id, amount, note) VALUES (?, ?, ?)",
                    (user_id, amount, "Выплата через админ-панель"))
    from fastapi.responses import RedirectResponse as RR
    return RR(f"/admin?key={key}&msg=Выплата+записана", status_code=303)


# ---------- health ----------

@app.get("/healthz")
def healthz():
    return {"status": "ok"}
