import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from database import engine
from models import Region, User, UserRegion
from security import parol_hashle, parol_yoxla

# database.py import edildikdə .env oxunur. Açar yoxdursa server işə düşmür.
GIZLI_ACAR = os.environ["JWT_SECRET"]
ALQORITM = "HS256"
TOKEN_MUDDETI = timedelta(days=7)

bearer = HTTPBearer(auto_error=False)
router = APIRouter()


class LoginData(BaseModel):
    login: str
    parol: str


class ParolDeyis(BaseModel):
    kohne_parol: str
    yeni_parol: str = Field(min_length=8)


def token_yarat(user: User) -> str:
    bitme = datetime.now(timezone.utc) + TOKEN_MUDDETI
    return jwt.encode(
        {"sub": str(user.id), "rol": user.rol, "exp": bitme},
        GIZLI_ACAR,
        algorithm=ALQORITM,
    )


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


@router.post("/auth/login")
def login(data: LoginData):
    with Session(engine) as session:
        user = session.exec(select(User).where(User.login == data.login)).first()
        if not user or not user.active or not parol_yoxla(data.parol, user.parol_hash):
            raise HTTPException(status_code=401, detail="Login və ya şifrə yanlışdır")
        return {"token": token_yarat(user), "ad": user.ad, "rol": user.rol}


@router.get("/me")
def me(user: User = Depends(cari_user)):
    with Session(engine) as session:
        regionlar = session.exec(
            select(Region.ad)
            .join(UserRegion, UserRegion.region_id == Region.id)
            .where(UserRegion.user_id == user.id, Region.active == True)  # noqa: E712
            .order_by(Region.ad)
        ).all()
    return {"id": user.id, "ad": user.ad, "rol": user.rol, "regionlar": list(regionlar)}


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


