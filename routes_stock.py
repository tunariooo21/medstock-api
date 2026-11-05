import calendar
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func
from sqlmodel import Session, select

from auth import rol_teleb_et
from database import engine
from models import (
    Clinic,
    Doctor,
    Medicine,
    Point,
    Prescription,
    Setting,
    StockMovement,
    User,
)
from routes_reference import istifadeci_regionlari
from routes_reports import BAKI, ay_oxu

router = APIRouter()
OXUYAN = rol_teleb_et("representative", "manager")

ASAGI_HEDD_ACARI = "asagi_qaliq_hedd"
STANDART_HEDD = 20
M = StockMovement


def bu_gun() -> date:
    return datetime.now(BAKI).date()


def ay_son_gunu(ay: date) -> date:
    return date(ay.year, ay.month, calendar.monthrange(ay.year, ay.month)[1])


def asagi_hedd(session: Session) -> int:
    setir = session.get(Setting, ASAGI_HEDD_ACARI)
    try:
        return int(setir.deyer) if setir else STANDART_HEDD
    except ValueError:
        return STANDART_HEDD


def qaliq_ifadesi():
    """Qalıq = daxilolmalar + geri qaytarmalar − satışlar."""
    return func.coalesce(
        func.sum(
            case(
                (M.novu.in_(("daxilolma", "geri_qaytarma")), M.say),
                (M.novu == "satis", -M.say),
                else_=0,
            )
        ),
        0,
    )


def status_tap(qaliq: int, hedd: int) -> str:
    if qaliq <= 0:
        return "sifir"
    if qaliq < hedd:
        return "az"
    return "normal"


def nokte_qaliqi(session: Session, point_id: int, medicine_id: int) -> int:
    return int(
        session.exec(
            select(qaliq_ifadesi()).where(
                M.point_id == point_id,
                M.medicine_id == medicine_id,
                M.tarix <= bu_gun(),
            )
        ).one()
    )


@router.get("/stock")
def stok(
    region: int = Query(..., description="Region id"),
    month: str | None = Query(default=None, description="YYYY-AA; boşdursa cari ay"),
    medicine: int | None = Query(
        default=None, description="Dərman id; boşdursa bütün dərmanlar"
    ),
    user: User = Depends(OXUYAN),
):
    bugun = bu_gun()
    ay = ay_oxu(month) if month else bugun.replace(day=1)
    if ay > bugun.replace(day=1):
        raise HTTPException(status_code=400, detail="Gələcək ay üçün məlumat yoxdur")
    bas = ay
    son = ay_son_gunu(ay)
    kesim = min(son, bugun)  # qalıq bu tarixə qədər hesablanır

    with Session(engine) as session:
        if region not in istifadeci_regionlari(session, user):
            raise HTTPException(status_code=403, detail="Bu region sənə təyin olunmayıb")

        # 'sira' /medicines ilə eynidir: dərmanın rəngi hər yerdə sabit qalır
        butun = session.exec(select(Medicine).order_by(Medicine.id)).all()
        dermanlar = [(sira, d) for sira, d in enumerate(butun) if d.active]
        if medicine is not None:
            dermanlar = [(s, d) for s, d in dermanlar if d.id == medicine]
            if not dermanlar:
                raise HTTPException(status_code=404, detail="Dərman tapılmadı")
        derman_idleri = [d.id for _, d in dermanlar]

        noqteler = session.exec(
            select(Point)
            .where(Point.region_id == region, Point.active == True)  # noqa: E712
            .order_by(Point.novu, Point.ad)
        ).all()
        idler = [p.id for p in noqteler]
        hedd = asagi_hedd(session)

        hereket: dict[tuple[int, int], tuple[int, int, int]] = {}
        resept: dict[tuple[int, int], int] = {}
        if idler and derman_idleri:
            sorgu = (
                select(
                    M.point_id,
                    M.medicine_id,
                    qaliq_ifadesi(),
                    func.coalesce(
                        func.sum(case((M.novu == "daxilolma", M.say), else_=0)), 0
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (and_(M.novu == "satis", M.tarix >= bas), M.say),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                )
                .where(
                    M.point_id.in_(idler),
                    M.medicine_id.in_(derman_idleri),
                    M.tarix <= kesim,
                )
                .group_by(M.point_id, M.medicine_id)
            )
            for pid, mid, q, d, s in session.exec(sorgu).all():
                hereket[(pid, mid)] = (int(q), int(d), int(s))

            resept = {
                (pid, mid): int(say)
                for pid, mid, say in session.exec(
                    select(
                        Prescription.point_id,
                        Prescription.medicine_id,
                        func.sum(Prescription.say),
                    )
                    .where(
                        Prescription.point_id.in_(idler),
                        Prescription.medicine_id.in_(derman_idleri),
                        Prescription.tarix >= bas,
                        Prescription.tarix <= kesim,
                    )
                    .group_by(Prescription.point_id, Prescription.medicine_id)
                ).all()
            }

        cemiler = {mid: [0, 0, 0] for mid in derman_idleri}
        kartlar = []
        for p in noqteler:
            satirlar = []
            for sira, d in dermanlar:
                q, dax, s = hereket.get((p.id, d.id), (0, 0, 0))
                r = resept.get((p.id, d.id), 0)
                satirlar.append(
                    {
                        "medicine_id": d.id,
                        "ad": d.ad,
                        "sira": sira,
                        "qaliq": q,
                        "daxilolma": dax,
                        "satilib": s,
                        "resept": r,
                        "status": status_tap(q, hedd),
                    }
                )
                cemiler[d.id][0] += q
                cemiler[d.id][1] += s
                cemiler[d.id][2] += r
            kartlar.append(
                {
                    "id": p.id,
                    "ad": p.ad,
                    "novu": p.novu,
                    "unvan": p.unvan,
                    "dermanlar": satirlar,
                }
            )

        return {
            "region_id": region,
            "ay": ay.strftime("%Y-%m"),
            "kesim": kesim.isoformat(),
            "cari_ay": kesim < son,
            "asagi_hedd": hedd,
            "cemi": [
                {
                    "medicine_id": d.id,
                    "ad": d.ad,
                    "sira": sira,
                    "qaliq": cemiler[d.id][0],
                    "satilib": cemiler[d.id][1],
                    "resept": cemiler[d.id][2],
                }
                for sira, d in dermanlar
            ],
            "noqteler": kartlar,
        }


# ---------- Qeyd əlavə etmək ----------


def tarix_yoxla(t: date | None) -> date:
    bugun = bu_gun()
    t = t or bugun
    if t > bugun:
        raise HTTPException(status_code=422, detail="Gələcək tarix yazmaq olmaz")
    return t


def nokte_yoxla(session: Session, point_id: int, user: User) -> Point:
    nokte = session.get(Point, point_id)
    if not nokte or not nokte.active:
        raise HTTPException(status_code=404, detail="Aptek/depo tapılmadı")
    if nokte.region_id not in istifadeci_regionlari(session, user):
        raise HTTPException(status_code=403, detail="Bu region sənə təyin olunmayıb")
    return nokte


def derman_yoxla(session: Session, medicine_id: int) -> Medicine:
    derman = session.get(Medicine, medicine_id)
    if not derman or not derman.active:
        raise HTTPException(status_code=404, detail="Dərman tapılmadı")
    return derman


class HereketGiris(BaseModel):
    point_id: int
    medicine_id: int
    novu: Literal["satis", "geri_qaytarma"]
    say: int = Field(gt=0, le=1_000_000)
    tarix: date | None = None
    sebeb: str | None = Field(default=None, max_length=300)


class ReseptGiris(BaseModel):
    point_id: int
    medicine_id: int
    doctor_id: int
    say: int = Field(gt=0, le=1_000_000)
    tarix: date | None = None


@router.post("/movements")
def hereket_yarat(data: HereketGiris, user: User = Depends(OXUYAN)):
    tarix = tarix_yoxla(data.tarix)
    with Session(engine) as session:
        nokte = nokte_yoxla(session, data.point_id, user)
        derman_yoxla(session, data.medicine_id)
        hereket = StockMovement(
            point_id=nokte.id,
            medicine_id=data.medicine_id,
            user_id=user.id,
            novu=data.novu,
            say=data.say,
            tarix=tarix,
            sebeb=(data.sebeb or "").strip() or None,
            created_by=user.id,
        )
        session.add(hereket)
        session.commit()
        session.refresh(hereket)
        return {
            "id": hereket.id,
            "qaliq": nokte_qaliqi(session, nokte.id, data.medicine_id),
        }


@router.post("/prescriptions")
def resept_yarat(data: ReseptGiris, user: User = Depends(OXUYAN)):
    tarix = tarix_yoxla(data.tarix)
    with Session(engine) as session:
        nokte = nokte_yoxla(session, data.point_id, user)
        derman_yoxla(session, data.medicine_id)

        regionlar = list(istifadeci_regionlari(session, user))
        hekim = session.exec(
            select(Doctor)
            .join(Clinic, Doctor.clinic_id == Clinic.id)
            .where(
                Doctor.id == data.doctor_id,
                Doctor.active == True,  # noqa: E712
                Clinic.active == True,  # noqa: E712
                Clinic.region_id.in_(regionlar or [-1]),
            )
        ).first()
        if not hekim:
            raise HTTPException(
                status_code=422, detail="Həkim tapılmadı və ya sənin regionunda deyil"
            )

        resept = Prescription(
            point_id=nokte.id,
            medicine_id=data.medicine_id,
            doctor_id=hekim.id,
            say=data.say,
            tarix=tarix,
            created_by=user.id,
        )
        session.add(resept)
        session.commit()
        session.refresh(resept)
        return {"id": resept.id}


@router.get("/me/recent")
def son_qeydler(
    limit: int = Query(default=10, ge=1, le=30),
    user: User = Depends(OXUYAN),
):
    """İstifadəçinin özünün son satış, geri qaytarma və resept qeydləri."""
    with Session(engine) as session:
        hereketler = session.exec(
            select(M, Medicine, Point)
            .join(Medicine, M.medicine_id == Medicine.id)
            .join(Point, M.point_id == Point.id)
            .where(M.user_id == user.id, M.novu.in_(("satis", "geri_qaytarma")))
            .order_by(M.created_at.desc())
            .limit(limit)
        ).all()
        reseptler = session.exec(
            select(Prescription, Medicine, Point)
            .join(Medicine, Prescription.medicine_id == Medicine.id)
            .join(Point, Prescription.point_id == Point.id)
            .where(Prescription.created_by == user.id)
            .order_by(Prescription.created_at.desc())
            .limit(limit)
        ).all()

        butun = [
            (m.created_at, m.novu, d.ad, p.ad, m.say, m.tarix)
            for m, d, p in hereketler
        ] + [
            (r.created_at, "resept", d.ad, p.ad, r.say, r.tarix)
            for r, d, p in reseptler
        ]
        butun.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "novu": novu,
                "derman": derman,
                "point_ad": point,
                "say": say,
                "tarix": tarix.isoformat(),
            }
            for _, novu, derman, point, say, tarix in butun[:limit]
        ]