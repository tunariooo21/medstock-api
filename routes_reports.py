import re
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from auth import rol_teleb_et
from database import engine
from models import Clinic, Doctor, Medicine, MonthlyReport, MonthlyReportRow, User
from routes_reference import istifadeci_regionlari

router = APIRouter()
NUMAYENDE = rol_teleb_et("representative")

REDAKTE_STATUSLARI = ("qaralama", "geri_qaytarildi")
BAKI = timezone(timedelta(hours=4))


def bu_ay() -> date:
    indi = datetime.now(BAKI)
    return date(indi.year, indi.month, 1)


def ay_oxu(metn: str) -> date:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", metn):
        raise HTTPException(
            status_code=422, detail="Ay formatı YYYY-AA olmalıdır (məs. 2026-10)"
        )
    il, ay = metn.split("-")
    return date(int(il), int(ay), 1)


class SetirGiris(BaseModel):
    doctor_id: int
    medicine_id: int
    say: int = Field(ge=0, le=100000)


class HesabatGiris(BaseModel):
    setirler: list[SetirGiris]


def hesabat_cavabi(session: Session, hesabat: MonthlyReport) -> dict:
    setirler = session.exec(
        select(MonthlyReportRow)
        .where(MonthlyReportRow.report_id == hesabat.id)
        .order_by(MonthlyReportRow.doctor_id, MonthlyReportRow.medicine_id)
    ).all()
    return {
        "id": hesabat.id,
        "ay": hesabat.ay.strftime("%Y-%m"),
        "status": hesabat.status,
        "menecer_serhi": hesabat.menecer_serhi,
        "redakte_oluna_biler": hesabat.status in REDAKTE_STATUSLARI,
        "setirler": [
            {"doctor_id": s.doctor_id, "medicine_id": s.medicine_id, "say": s.say}
            for s in setirler
        ],
    }


def hesabat_tap(session: Session, hesabat_id: int, user: User) -> MonthlyReport:
    hesabat = session.get(MonthlyReport, hesabat_id)
    if not hesabat:
        raise HTTPException(status_code=404, detail="Hesabat tapılmadı")
    if hesabat.user_id != user.id:
        raise HTTPException(status_code=403, detail="Bu hesabat sənə aid deyil")
    return hesabat


@router.get("/reports/monthly")
def hesabat_oxu(
    month: str | None = Query(default=None, description="YYYY-AA; boşdursa cari ay"),
    user: User = Depends(NUMAYENDE),
):
    ay = ay_oxu(month) if month else bu_ay()
    if ay > bu_ay():
        raise HTTPException(
            status_code=400, detail="Gələcək ay üçün hesabat yaratmaq olmaz"
        )
    with Session(engine) as session:
        sorgu = select(MonthlyReport).where(
            MonthlyReport.user_id == user.id, MonthlyReport.ay == ay
        )
        hesabat = session.exec(sorgu).first()
        if not hesabat:
            hesabat = MonthlyReport(user_id=user.id, ay=ay, created_by=user.id)
            session.add(hesabat)
            try:
                session.commit()
            except IntegrityError:  # eyni anda iki sorğu gəlibsə
                session.rollback()
                hesabat = session.exec(sorgu).first()
            else:
                session.refresh(hesabat)
        return hesabat_cavabi(session, hesabat)


@router.put("/reports/monthly/{hesabat_id}")
def hesabat_saxla(
    hesabat_id: int, data: HesabatGiris, user: User = Depends(NUMAYENDE)
):
    with Session(engine) as session:
        hesabat = hesabat_tap(session, hesabat_id, user)
        if hesabat.status not in REDAKTE_STATUSLARI:
            raise HTTPException(
                status_code=409, detail="Bu hesabat artıq redaktə oluna bilməz"
            )

        cutler = [(s.doctor_id, s.medicine_id) for s in data.setirler]
        if len(set(cutler)) != len(cutler):
            raise HTTPException(
                status_code=422, detail="Eyni həkim və dərman təkrarlanır"
            )

        # İstifadəçinin regionlarındakı aktiv həkimlər
        regionlar = list(istifadeci_regionlari(session, user))
        icazeli_hekimler: set[int] = set()
        if regionlar:
            icazeli_hekimler = set(
                session.exec(
                    select(Doctor.id)
                    .join(Clinic, Doctor.clinic_id == Clinic.id)
                    .where(
                        Doctor.active == True,  # noqa: E712
                        Clinic.active == True,  # noqa: E712
                        Clinic.region_id.in_(regionlar),
                    )
                ).all()
            )
        aktiv_dermanlar = set(
            session.exec(
                select(Medicine.id).where(Medicine.active == True)  # noqa: E712
            ).all()
        )

        for s in data.setirler:
            if s.doctor_id not in icazeli_hekimler:
                raise HTTPException(
                    status_code=422,
                    detail=f"Həkim {s.doctor_id} tapılmadı və ya sənin regionunda deyil",
                )
            if s.medicine_id not in aktiv_dermanlar:
                raise HTTPException(
                    status_code=422,
                    detail=f"Dərman {s.medicine_id} tapılmadı və ya aktiv deyil",
                )

        # Yalnız indi görünən (aktiv) həkimlərin sətirləri əvəz olunur;
        # sonradan deaktiv edilmiş həkimin köhnə qeydləri toxunulmaz qalır.
        if icazeli_hekimler:
            session.execute(
                delete(MonthlyReportRow).where(
                    MonthlyReportRow.report_id == hesabat.id,
                    MonthlyReportRow.doctor_id.in_(icazeli_hekimler),
                )
            )
        for s in data.setirler:
            if s.say > 0:
                session.add(
                    MonthlyReportRow(
                        report_id=hesabat.id,
                        doctor_id=s.doctor_id,
                        medicine_id=s.medicine_id,
                        say=s.say,
                        created_by=user.id,
                    )
                )
        session.commit()
        session.refresh(hesabat)
        return hesabat_cavabi(session, hesabat)


@router.post("/reports/monthly/{hesabat_id}/submit")
def hesabat_gonder(hesabat_id: int, user: User = Depends(NUMAYENDE)):
    with Session(engine) as session:
        hesabat = hesabat_tap(session, hesabat_id, user)
        if hesabat.status not in REDAKTE_STATUSLARI:
            raise HTTPException(
                status_code=409, detail="Bu hesabat artıq göndərilib"
            )
        bos = (
            session.exec(
                select(MonthlyReportRow.id)
                .where(MonthlyReportRow.report_id == hesabat.id, MonthlyReportRow.say > 0)
                .limit(1)
            ).first()
            is None
        )
        if bos:
            raise HTTPException(
                status_code=422, detail="Boş hesabatı göndərmək olmaz"
            )
        hesabat.status = "gonderildi"
        session.add(hesabat)
        session.commit()
        session.refresh(hesabat)
        return hesabat_cavabi(session, hesabat)