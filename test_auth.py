"""Müvəqqəti smoke test: auth axını SQLite üzərində."""

import os
import pathlib

os.environ["DATABASE_URL"] = "sqlite:///./smoke.db"
os.environ["JWT_SECRET"] = "smoke-test-secret"

import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

import auth as auth_mod  # noqa: E402
from database import engine  # noqa: E402

pathlib.Path("smoke.db").unlink(missing_ok=True)
SQLModel.metadata.create_all(engine)

app = FastAPI()
app.include_router(auth_mod.router)
c = TestClient(app)


def yoxla(sert, mesaj):
    if not sert:
        raise SystemExit("FAIL: " + mesaj)
    print("ok:", mesaj)


r = c.post(
    "/auth/register",
    json={
        "ad": "Elvin Hüseynov",
        "login": "elvin",
        "email": "elvin@example.com",
        "parol": "parol1234",
    },
)
yoxla(r.status_code == 200, f"register 200 ({r.status_code}: {r.text[:120]})")
token = r.json()["token"]

r = c.post(
    "/auth/register",
    json={
        "ad": "Başqa",
        "login": "elvin",
        "email": "baska@example.com",
        "parol": "parol1234",
    },
)
yoxla(r.status_code == 409, "register dublikat 409")

r = c.get("/me", headers={"Authorization": f"Bearer {token}"})
yoxla(r.status_code == 200 and r.json()["email"] == "elvin@example.com", "me email")
yoxla(r.json()["login"] == "elvin", "me login")

r = c.post("/auth/login", json={"login": "elvin@example.com", "parol": "parol1234"})
yoxla(r.status_code == 200, "login email ilə")

r = c.post("/auth/forgot-password", json={"email": "elvin@example.com"})
yoxla(r.status_code == 200 and r.json().get("demo") is True, "forgot demo rejimi")
kod = r.json()["kod"]
yoxla(len(kod) == 6 and kod.isdigit(), "6 rəqəmli kod")

r = c.post("/auth/forgot-password", json={"email": "elvin@example.com"})
yoxla(r.status_code == 429, "forgot rate limit 429")

yanlis = "000000" if kod != "000000" else "111111"
r = c.post("/auth/verify-code", json={"email": "elvin@example.com", "kod": yanlis})
yoxla(r.status_code == 400, "yanlış kod 400")

r = c.post("/auth/verify-code", json={"email": "elvin@example.com", "kod": kod})
yoxla(r.status_code == 200, "verify-code 200")
reset_token = r.json()["reset_token"]

r = c.post(
    "/auth/reset-password",
    json={"reset_token": reset_token, "yeni_parol": "yenisifre99"},
)
yoxla(r.status_code == 200, "reset-password 200")

r = c.post("/auth/login", json={"login": "elvin", "parol": "yenisifre99"})
yoxla(r.status_code == 200, "yeni şifrə ilə login")
token = r.json()["token"]

r = c.put(
    "/me/profile",
    headers={"Authorization": f"Bearer {token}"},
    json={"ad": "Elvin H.", "telefon": "+994 50 555 55 55", "whatsapp": "+994505555555"},
)
yoxla(r.status_code == 200 and r.json()["telefon"].startswith("+994"), "profil yeniləndi")

r = c.put(
    "/me/profile",
    headers={"Authorization": f"Bearer {token}"},
    json={"ad": "Elvin H.", "telefon": "abc", "whatsapp": ""},
)
yoxla(r.status_code == 400, "yanlış telefon 400")

r = c.post(
    "/me/password",
    headers={"Authorization": f"Bearer {token}"},
    json={"kohne_parol": "yenisifre99", "yeni_parol": "sonparol123"},
)
yoxla(r.status_code == 200, "parol dəyişdi")

r = c.post("/auth/login", json={"login": "elvin", "parol": "sonparol123"})
yoxla(r.status_code == 200, "son şifrə ilə login")

print("\nBÜTÜN TESTLƏR KEÇDİ")
