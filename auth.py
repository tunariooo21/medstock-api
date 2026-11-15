import hashlib
import hmac
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

import email_service
from database import engine
from models import PasswordReset, Region, User, UserRegion
from security import parol_hashle, parol_yoxla

# database.py import edildikdə .env oxunur. Açar yoxdursa server işə düşmür.
GIZLI_ACAR = os.environ["JWT_SECRET"]
ALQORITM = "HS256"
TOKEN_MUDDETI = timedelta(days=7)

KOD_MUDDETI = timedelta(minutes=15)
KOD_TEKRAR_MEHDUDIYYETI = timedelta(seconds=60)
RESET_TOKEN_MUDDETI = timedelta(minutes=10)

LOGIN_RE = re.compile(r"^[\w.\-]{3,32}$", re.UNICODE)
TELEFON_RE = re.compile(r"^\+?[0-9][0-9\s\-()]{6,19}$")

bearer = HTTPBearer(auto_error=False)
router = APIRouter()
logger = logging.getLogger("medstock.auth")


class LoginData(BaseModel):
    login: str
    parol: str


class RegisterData(BaseModel):
    ad: str = Field(min_length=2, max_length=80)
    login: str = Field(min_length=3, max_length=32)
    email: EmailStr
    parol: str = Field(min_length=8, max_length=72)


class ParolDeyis(BaseModel):
    kohne_parol: str
    yeni_parol: str = Field(min_length=8)


class EmailData(BaseModel):
    email: EmailStr


class KodData(BaseModel):
    email: EmailStr
    kod: str = Field(min_length=6, max_length=6)


class YeniParolData(BaseModel):
    reset_token: str
    yeni_parol: str = Field(min_length=8)


class ProfilData(BaseModel):
    ad: str = Field(min_length=2, max_length=80)
    telefon: str | None = None
    whatsapp: str | None = None


def token_yarat(user: User) -> str:
    bitme = datetime.now(timezone.utc) + TOKEN_MUDDETI
    return jwt.encode(
        {"sub": str(user.id), "rol": user.rol, "exp": bitme},
        GIZLI_ACAR,
        algorithm=ALQORITM,
    )


def reset_token_yarat(user: User) -> str:
    bitme = datetime.now(timezone.utc) + RESET_TOKEN_MUDDETI
    return jwt.encode(
        {"sub": str(user.id), "typ": "parol", "exp": bitme},
        GIZLI_ACAR,
        algorithm=ALQORITM,
    )


def kod_hashle(kod: str) -> str:
    return hmac.new(GIZLI_ACAR.encode(), kod.encode(), hashlib.sha256).hexdigest()


def _utc(deyer: datetime) -> datetime:
    """SQLite naiv datetime qaytarır; müqayisə üçün UTC kimi qəbul edirik."""
    return deyer if deyer.tzinfo else deyer.replace(tzinfo=timezone.utc)


def cari_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
    """Tokeni yoxlayır və istifadəçini qaytarır. Token yoxdursa 401."""
    if creds is None:
        raise HTTPException(status_code=401, detail="Token tələb olunur")
    try:
        mezmun = jwt.decode(creds.credentials, GIZLI_ACAR, algorithms=[ALQORITM])
        user_id = int(mezmun["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Token yanlışdır və ya vaxtı bitib")
    with Session(engine) as session:
        user = session.get(User, user_id)
        if not user or not user.active:
            raise HTTPException(status_code=401, detail="Hesab tapılmadı və ya deaktivdir")
        return user


def rol_teleb_et(*roller: str):
    """Rolu yoxlayan dependency: icazəsi yoxdursa 403."""

    def yoxla(user: User = Depends(cari_user)) -> User:
        if user.rol not in roller:
            raise HTTPException(status_code=403, detail="Bu əməliyyat üçün icazən yoxdur")
        return user

    return yoxla


def _me_data(user: User) -> dict:
    with Session(engine) as session:
        regionlar = session.exec(
            select(Region.ad)
            .join(UserRegion, UserRegion.region_id == Region.id)
            .where(UserRegion.user_id == user.id, Region.active == True)  # noqa: E712
            .order_by(Region.ad)
        ).all()
    return {
        "id": user.id,
        "ad": user.ad,
        "login": user.login,
        "email": user.email,
        "telefon": user.telefon,
        "whatsapp": user.whatsapp,
        "rol": user.rol,
        "regionlar": list(regionlar),
    }


def _telefon_temizle(deyer: str | None, sahe: str) -> str | None:
    if deyer is None:
        return None
    temiz = deyer.strip()
    if not temiz:
        return None
    if not TELEFON_RE.fullmatch(temiz):
        raise HTTPException(status_code=400, detail=f"{sahe} düzgün formatda deyil")
    return temiz


@router.post("/auth/login")
def login(data: LoginData):
    kimlik = data.login.strip()
    with Session(engine) as session:
        user = session.exec(
            select(User).where(
                (User.login == kimlik) | (User.email == kimlik.lower())
            )
        ).first()
        if not user or not user.active or not parol_yoxla(data.parol, user.parol_hash):
            raise HTTPException(status_code=401, detail="Login və ya şifrə yanlışdır")
        return {"token": token_yarat(user)}


@router.post("/auth/register")
def register(data: RegisterData):
    login = data.login.strip()
    email = data.email.lower()
    if not LOGIN_RE.fullmatch(login):
        raise HTTPException(
            status_code=400,
            detail="İstifadəçi adı 3–32 simvol olmalı və boşluq içerməməlidir",
        )
    with Session(engine) as session:
        movcud = session.exec(
            select(User).where((User.login == login) | (User.email == email))
        ).first()
        if movcud:
            if movcud.login == login:
                raise HTTPException(
                    status_code=409, detail="Bu istifadəçi adı artıq mövcuddur"
                )
            raise HTTPException(
                status_code=409, detail="Bu e-poçt ilə hesab artıq mövcuddur"
            )
        user = User(
            login=login,
            ad=data.ad.strip(),
            rol="representative",
            parol_hash=parol_hashle(data.parol),
            email=email,
        )
        session.add(user)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(status_code=409, detail="Bu hesab artıq mövcuddur")
        session.refresh(user)
        return {"token": token_yarat(user), "ad": user.ad, "rol": user.rol}


@router.post("/auth/forgot-password")
def parolu_unutdum(data: EmailData):
    email = data.email.lower()
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
        if not user or not user.active:
            # Hesabın mövcudluğunu bildirmirik.
            return {"mesaj": "Əgər bu e-poçt qeydiyyatdadırsa, kod göndərildi", "demo": False}

        son = session.exec(
            select(PasswordReset)
            .where(PasswordReset.user_id == user.id)
            .order_by(PasswordReset.created_at.desc())
        ).first()
        indi = datetime.now(timezone.utc)
        if son and indi - _utc(son.created_at) < KOD_TEKRAR_MEHDUDIYYETI:
            qalan = int(
                (KOD_TEKRAR_MEHDUDIYYETI - (indi - _utc(son.created_at))).total_seconds()
            ) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Yeni kod üçün {qalan} saniyə gözləyin",
            )

        kod = f"{secrets.randbelow(1_000_000):06d}"
        qeyd = PasswordReset(
            user_id=user.id,
            kod_hash=kod_hashle(kod),
            bitme=indi + KOD_MUDDETI,
        )
        session.add(qeyd)
        session.commit()
        ad = user.ad

    if not email_service.konfiqurasiya_var():
        # Demo rejimi: SMTP qurulmayıb, kod cavabda qaytarılır.
        return {
            "mesaj": "Demo rejimi: təsdiq kodu aşağıdadır",
            "demo": True,
            "kod": kod,
        }

    try:
        email_service.kod_gonder(email, kod, ad)
    except email_service.EmailXetasi as xeta:
        logger.exception("SMTP göndərişi alınmadı: %s", xeta)
        raise HTTPException(
            status_code=502,
            detail="E-poçt göndərilmədi. Bir az sonra yenidən cəhd edin",
        )
    return {"mesaj": "Təsdiq kodu e-poçtunuza göndərildi", "demo": False}


@router.post("/auth/verify-code")
def kodu_yoxla(data: KodData):
    email = data.email.lower()
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
        if not user or not user.active:
            raise HTTPException(status_code=400, detail="Kod yanlışdır və ya vaxtı bitib")

        qeyd = session.exec(
            select(PasswordReset)
            .where(
                PasswordReset.user_id == user.id,
                PasswordReset.istifade == False,  # noqa: E712
            )
            .order_by(PasswordReset.created_at.desc())
        ).first()
        if not qeyd:
            raise HTTPException(status_code=400, detail="Kod yanlışdır və ya vaxtı bitib")

        indi = datetime.now(timezone.utc)
        bitme = _utc(qeyd.bitme)
        if bitme < indi:
            raise HTTPException(status_code=400, detail="Kodun vaxtı bitib")

        if qeyd.cehd >= 5:
            raise HTTPException(
                status_code=429, detail="Çox cəhd edildi. Yeni kod istəyin"
            )
        if not hmac.compare_digest(qeyd.kod_hash, kod_hashle(data.kod.strip())):
            qeyd.cehd += 1
            session.add(qeyd)
            session.commit()
            raise HTTPException(status_code=400, detail="Kod yanlışdır")

        qeyd.istifade = True
        session.add(qeyd)
        session.commit()
        return {"reset_token": reset_token_yarat(user)}


@router.post("/auth/reset-password")
def parolu_sifirla(data: YeniParolData):
    try:
        mezmun = jwt.decode(data.reset_token, GIZLI_ACAR, algorithms=[ALQORITM])
        if mezmun.get("typ") != "parol":
            raise ValueError
        user_id = int(mezmun["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(
            status_code=400, detail="Kodun vaxtı bitib. Yenidən kod istəyin"
        )

    with Session(engine) as session:
        user = session.get(User, user_id)
        if not user or not user.active:
            raise HTTPException(status_code=401, detail="Hesab tapılmadı")
        user.parol_hash = parol_hashle(data.yeni_parol)
        session.add(user)
        for qeyd in session.exec(
            select(PasswordReset).where(
                PasswordReset.user_id == user.id,
                PasswordReset.istifade == False,  # noqa: E712
            )
        ).all():
            qeyd.istifade = True
            session.add(qeyd)
        session.commit()
    return {"mesaj": "Şifrəniz yeniləndi"}


@router.get("/me")
def me(user: User = Depends(cari_user)):
    return _me_data(user)


@router.put("/me/profile")
def profil_yenile(data: ProfilData, user: User = Depends(cari_user)):
    with Session(engine) as session:
        db_user = session.get(User, user.id)
        db_user.ad = data.ad.strip()
        db_user.telefon = _telefon_temizle(data.telefon, "Əlaqə nömrəsi")
        db_user.whatsapp = _telefon_temizle(data.whatsapp, "WhatsApp nömrəsi")
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
        return _me_data(db_user)


@router.post("/me/password")
def parol_deyis(data: ParolDeyis, user: User = Depends(cari_user)):
    if not parol_yoxla(data.kohne_parol, user.parol_hash):
        raise HTTPException(status_code=400, detail="Köhnə şifrə yanlışdır")
    with Session(engine) as session:
        db_user = session.get(User, user.id)
        db_user.parol_hash = parol_hashle(data.yeni_parol)
        session.add(db_user)
        session.commit()
    return {"mesaj": "Şifrə dəyişdirildi"}
