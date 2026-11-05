from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select

from auth import rol_teleb_et
from database import engine
from models import (
    Clinic,
    Doctor,
    Medicine,
    MonthlyReport,
    MonthlyReportRow,
    Point,
    StockMovement,
    User,
)

from routes_reports import ay_oxu, bu_ay

router = APIRouter()
MENECER = rol_teleb_et("manager")

# Qaralama menecerə görünmür
GORUNEN = ("gonderildi", "geri_qaytarildi", "tesdiqlendi")


def isci_hesabati_tap(session: Session, hesabat_id: int, menecer: User):
    """Hesabatı tapır və onun menecerin öz işçisinə aid olduğunu yoxlayır."""
    hesabat = session.get(MonthlyReport, hesabat_id)
    if not hesabat:
        raise HTTPException(status_code=404, detail="Hesabat tapılmadı")
    sahib = session.get(User, hesabat.user_id)
    if not sahib or sahib.manager_id != menecer.id:
        raise HTTPException(
            status_code=403, detail="Bu hesabat sənin işçinə aid deyil"
        )
    return hesabat, sahib


@router.get("/manager/reports")
def isci_hesabatlari(
    month: str | None = Query(default=None, description="YYYY-AA; boşdursa cari ay"),
    user: User = Depends(MENECER),
):
    ay = ay_oxu(month) if month else bu_ay()
    if ay > bu_ay():
        raise HTTPException(status_code=400, detail="Gələcək ay üçün məlumat yoxdur")

    with Session(engine) as session:
        iscilar = session.exec(
            select(User)
            .where(User.manager_id == user.id, User.active == True)  # noqa: E712
            .order_by(User.ad)
        ).all()
        idler = [i.id for i in iscilar]

        hesabatlar: dict[int, MonthlyReport] = {}
        if idler:
            for h in session.exec(
                select(MonthlyReport).where(
                    MonthlyReport.user_id.in_(idler), MonthlyReport.ay == ay
                )
            ).all():
                hesabatlar[h.user_id] = h

        gorunen_idler = [h.id for h in hesabatlar.values() if h.status in GORUNEN]
        cemler: dict[int, int] = {}
        if gorunen_idler:
            cemler = {
                rid: int(c)
                for rid, c in session.exec(
                    select(MonthlyReportRow.report_id, func.sum(MonthlyReportRow.say))
                    .where(MonthlyReportRow.report_id.in_(gorunen_idler))
                    .group_by(MonthlyReportRow.report_id)
                ).all()
            }

        netice = []
        for i in iscilar:
            h = hesabatlar.get(i.id)
            gorunur = h is not None and h.status in GORUNEN
            netice.append(
                {
                    "user_id": i.id,
                    "ad": i.ad,
                    "hesabat_id": h.id if gorunur else None,
                    "status": h.status if h else "yoxdur",
                    "cemi": cemler.get(h.id, 0) if gorunur else None,
                }
            )
        return {"ay": ay.strftime("%Y-%m"), "iscilar": netice}


@router.get("/manager/reports/{hesabat_id}")
def hesabat_detali(hesabat_id: int, user: User = Depends(MENECER)):
    with Session(engine) as session:
        hesabat, sahib = isci_hesabati_tap(session, hesabat_id, user)
        if hesabat.status not in GORUNEN:
            raise HTTPException(status_code=409, detail="Hesabat hələ göndərilməyib")

        butun = session.exec(select(Medicine).order_by(Medicine.id)).all()
        sira = {d.id: i for i, d in enumerate(butun)}
        ad_xeritesi = {d.id: d.ad for d in butun}

        setirler = session.exec(
            select(MonthlyReportRow, Doctor, Clinic)
            .join(Doctor, MonthlyReportRow.doctor_id == Doctor.id)
            .join(Clinic, Doctor.clinic_id == Clinic.id)
            .where(MonthlyReportRow.report_id == hesabat.id)
            .order_by(Clinic.ad, Doctor.ad, MonthlyReportRow.medicine_id)
        ).all()

        hekimler: dict[int, dict] = {}
        derman_cemleri: dict[int, int] = {}
        for row, hekim, klinika in setirler:
            h = hekimler.setdefault(
                hekim.id,
                {
                    "id": hekim.id,
                    "ad": hekim.ad,
                    "ixtisas": hekim.ixtisas,
                    "clinic_ad": klinika.ad,
                    "cemi": 0,
                    "dermanlar": [],
                },
            )
            h["dermanlar"].append({"medicine_id": row.medicine_id, "say": row.say})
            h["cemi"] += row.say
            derman_cemleri[row.medicine_id] = (
                derman_cemleri.get(row.medicine_id, 0) + row.say
            )

        return {
            "id": hesabat.id,
            "user_id": sahib.id,
            "isci_ad": sahib.ad,
            "ay": hesabat.ay.strftime("%Y-%m"),
            "status": hesabat.status,
            "menecer_serhi": hesabat.menecer_serhi,
            "cemi": sum(derman_cemleri.values()),
            "dermanlar": [
                {
                    "medicine_id": mid,
                    "ad": ad_xeritesi.get(mid, "?"),
                    "sira": sira.get(mid, 0),
                    "cemi": c,
                }
                for mid, c in sorted(derman_cemleri.items())
            ],
            "hekimler": list(hekimler.values()),
        }


@router.post("/manager/reports/{hesabat_id}/approve")
def tesdiqle(hesabat_id: int, user: User = Depends(MENECER)):
    with Session(engine) as session:
        hesabat, _ = isci_hesabati_tap(session, hesabat_id, user)
        if hesabat.status != "gonderildi":
            raise HTTPException(
                status_code=409, detail="Yalnız göndərilmiş hesabat təsdiqlənə bilər"
            )
        hesabat.status = "tesdiqlendi"
        session.add(hesabat)
        session.commit()
        return {"id": hesabat.id, "status": hesabat.status}


class GeriQaytarmaGiris(BaseModel):
    serh: str = Field(min_length=1, max_length=500)


@router.post("/manager/reports/{hesabat_id}/return")
def geri_qaytar(
    hesabat_id: int, data: GeriQaytarmaGiris, user: User = Depends(MENECER)
):
    serh = data.serh.strip()
    if not serh:
        raise HTTPException(status_code=422, detail="Şərh yazmaq tələb olunur")
    with Session(engine) as session:
        hesabat, _ = isci_hesabati_tap(session, hesabat_id, user)
        if hesabat.status != "gonderildi":
            raise HTTPException(
                status_code=409,
                detail="Yalnız göndərilmiş hesabat geri qaytarıla bilər",
            )
        hesabat.status = "geri_qaytarildi"
        hesabat.menecer_serhi = serh
        session.add(hesabat)
        session.commit()
        return {"id": hesabat.id, "status": hesabat.status}


@router.get("/manager/returns")
def geri_qaytarmalar(
    month: str | None = Query(default=None, description="YYYY-AA; boşdursa cari ay"),
    user: User = Depends(MENECER),
):
    ay = ay_oxu(month) if month else bu_ay()
    if ay > bu_ay():
        raise HTTPException(status_code=400, detail="Gələcək ay üçün məlumat yoxdur")
    sonraki = date(ay.year + (ay.month == 12), ay.month % 12 + 1, 1)

    with Session(engine) as session:
        idler = list(
            session.exec(select(User.id).where(User.manager_id == user.id)).all()
        ) + [user.id]

        sert = (
            StockMovement.novu == "geri_qaytarma",
            StockMovement.user_id.in_(idler),
            StockMovement.tarix >= ay,
            StockMovement.tarix < sonraki,
        )

        setirler = session.exec(
            select(StockMovement, Medicine, Point, User)
            .join(Medicine, StockMovement.medicine_id == Medicine.id)
            .join(Point, StockMovement.point_id == Point.id)
            .join(User, StockMovement.user_id == User.id)
            .where(*sert)
            .order_by(StockMovement.tarix.desc(), StockMovement.id.desc())
        ).all()

        cemi = session.exec(
            select(func.coalesce(func.sum(StockMovement.say), 0)).where(*sert)
        ).one()

        derman_cemleri = session.exec(
            select(Medicine.id, Medicine.ad, func.sum(StockMovement.say))
            .select_from(StockMovement)
            .join(Medicine, StockMovement.medicine_id == Medicine.id)
            .where(*sert)
            .group_by(Medicine.id, Medicine.ad)
            .order_by(Medicine.id)
        ).all()

        return {
            "ay": ay.strftime("%Y-%m"),
            "cemi": int(cemi),
            "dermanlar": [
                {"medicine_id": mid, "ad": ad, "cemi": int(c)}
                for mid, ad, c in derman_cemleri
            ],
            "siyahi": [
                {
                    "id": m.id,
                    "tarix": m.tarix.isoformat(),
                    "derman": d.ad,
                    "point_ad": p.ad,
                    "point_novu": p.novu,
                    "say": m.say,
                    "sebeb": m.sebeb,
                    "isci_ad": u.ad,
                }
                for m, d, p, u in setirler
            ],
        }