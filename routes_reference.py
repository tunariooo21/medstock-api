from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from auth import rol_teleb_et
from database import engine
from models import Clinic, Doctor, Medicine, Region, User, UserRegion

router = APIRouter()
OXUYAN = rol_teleb_et("representative", "manager")


def istifadeci_regionlari(session: Session, user: User) -> dict[int, str]:
    """İstifadəçiyə təyin olunmuş aktiv regionlar: {id: ad}."""
    setirler = session.exec(
        select(Region.id, Region.ad)
        .join(UserRegion, UserRegion.region_id == Region.id)
        .where(UserRegion.user_id == user.id, Region.active == True)  # noqa: E712
        .order_by(Region.ad)
    ).all()
    return {region_id: ad for region_id, ad in setirler}


@router.get("/regions")
def regionlar(user: User = Depends(OXUYAN)):
    with Session(engine) as session:
        return [
            {"id": region_id, "ad": ad}
            for region_id, ad in istifadeci_regionlari(session, user).items()
        ]


@router.get("/medicines")
def dermanlar(user: User = Depends(OXUYAN)):
    """Aktiv dərmanlar. 'sira' rəngin sabit qalması üçündür: A həmişə eyni rəngdədir."""
    with Session(engine) as session:
        hamisi = session.exec(select(Medicine).order_by(Medicine.id)).all()
    return [
        {"id": d.id, "ad": d.ad, "forma": d.forma, "sira": sira}
        for sira, d in enumerate(hamisi)
        if d.active
    ]


@router.get("/doctors")
def hekimler(
    region: int | None = Query(default=None),
    user: User = Depends(OXUYAN),
):
    with Session(engine) as session:
        icazeli = istifadeci_regionlari(session, user)
        if region is not None and region not in icazeli:
            raise HTTPException(status_code=403, detail="Bu region sənə təyin olunmayıb")
        region_idleri = [region] if region is not None else list(icazeli)

        setirler = session.exec(
            select(Doctor, Clinic)
            .join(Clinic, Doctor.clinic_id == Clinic.id)
            .where(
                Doctor.active == True,  # noqa: E712
                Clinic.active == True,  # noqa: E712
                Clinic.region_id.in_(region_idleri),
            )
            .order_by(Clinic.ad, Doctor.ad)
        ).all()

    return [
        {
            "id": d.id,
            "ad": d.ad,
            "ixtisas": d.ixtisas,
            "telefon": d.telefon,
            "clinic_id": c.id,
            "clinic_ad": c.ad,
            "region_id": c.region_id,
        }
        for d, c in setirler
    ]