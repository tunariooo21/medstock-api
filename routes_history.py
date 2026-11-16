import calendar
import io
import json
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select

from auth import rol_teleb_et
from database import engine
from models import (
    Doctor,
    Medicine,
    MedicinePrice,
    Point,
    Prescription,
    RecordAudit,
    StockMovement,
    User,
)
from routes_reference import istifadeci_regionlari
from routes_reports import BAKI, ay_oxu

router = APIRouter()
OXUYAN = rol_teleb_et("representative", "manager")

M = StockMovement
LIMIT = 500

NOVLAR = {
    "satis": "Satış",
    "geri_qaytarma": "Geri qaytarma",
    "daxilolma": "Daxilolma",
    "resept": "Resept",
}


def bu_gun() -> date:
    return datetime.now(BAKI).date()


def ay_son_gunu(ay: date) -> date:
    return date(ay.year, ay.month, calendar.monthrange(ay.year, ay.month)[1])


def catma_icazesi_var(user: User, created_by: int | None) -> bool:
    return user.rol == "manager" or created_by == user.id


def region_yoxla(session: Session, region: int, user: User) -> str:
    regionlar = istifadeci_regionlari(session, user)
    if region not in regionlar:
        raise HTTPException(status_code=403, detail="Bu region sənə təyin olunmayıb")
    return regionlar[region]


def hereket_kart(m: M, d: Medicine, p: Point, yaradan: User | None) -> dict:
    return {
        "entity": "movement",
        "id": m.id,
        "point_id": p.id,
        "novu": m.novu,
        "derman": d.ad,
        "point_ad": p.ad,
        "say": m.say,
        "tarix": m.tarix.isoformat(),
        "sebeb": m.sebeb,
        "user_ad": yaradan.ad if yaradan else None,
        "created_by": m.created_by,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def resept_kart(
    r: Prescription, d: Medicine, p: Point, h: Doctor | None, yaradan: User | None
) -> dict:
    return {
        "entity": "prescription",
        "id": r.id,
        "point_id": p.id,
        "novu": "resept",
        "derman": d.ad,
        "point_ad": p.ad,
        "say": r.say,
        "tarix": r.tarix.isoformat(),
        "hekim": h.ad if h else None,
        "sebeb": None,
        "user_ad": yaradan.ad if yaradan else None,
        "created_by": r.created_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def tarixce_sorgula(
    session: Session, region: int, point_id: int | None, ay: date | None
) -> list[dict]:
    bas = ay or date(2000, 1, 1)
    son = ay_son_gunu(ay) if ay else bu_gun()

    hereket_sorgu = (
        select(M, Medicine, Point, User)
        .join(Medicine, M.medicine_id == Medicine.id)
        .join(Point, M.point_id == Point.id)
        .outerjoin(User, M.created_by == User.id)
        .where(
            Point.region_id == region,
            Point.active == True,  # noqa: E712
            M.tarix >= bas,
            M.tarix <= son,
        )
    )
    if point_id is not None:
        hereket_sorgu = hereket_sorgu.where(M.point_id == point_id)

    resept_sorgu = (
        select(Prescription, Medicine, Point, Doctor, User)
        .join(Medicine, Prescription.medicine_id == Medicine.id)
        .join(Point, Prescription.point_id == Point.id)
        .outerjoin(Doctor, Prescription.doctor_id == Doctor.id)
        .outerjoin(User, Prescription.created_by == User.id)
        .where(
            Point.region_id == region,
            Point.active == True,  # noqa: E712
            Prescription.tarix >= bas,
            Prescription.tarix <= son,
        )
    )
    if point_id is not None:
        resept_sorgu = resept_sorgu.where(Prescription.point_id == point_id)

    kartlar = [
        hereket_kart(m, d, p, u)
        for m, d, p, u in session.exec(hereket_sorgu).all()
    ] + [
        resept_kart(r, d, p, h, u)
        for r, d, p, h, u in session.exec(resept_sorgu).all()
    ]
    kartlar.sort(key=lambda k: (k["tarix"], k["created_at"] or ""), reverse=True)
    return kartlar


@router.get("/history")
def tarixce(
    region: int = Query(..., description="Region id"),
    point_id: int | None = Query(default=None),
    month: str | None = Query(default=None, description="YYYY-AA; boşdursa bütün tarixçə"),
    novu: str | None = Query(
        default=None, description="satis, geri_qaytarma, daxilolma, resept"
    ),
    user: User = Depends(OXUYAN),
):
    if novu is not None and novu not in NOVLAR:
        raise HTTPException(status_code=422, detail="Növ düzgün deyil")
    ay = ay_oxu(month) if month else None
    with Session(engine) as session:
        region_yoxla(session, region, user)
        kartlar = tarixce_sorgula(session, region, point_id, ay)
        if novu is not None:
            kartlar = [k for k in kartlar if k["novu"] == novu]
        for k in kartlar:
            k["duzeldilebilir"] = catma_icazesi_var(user, k["created_by"])
        return kartlar[:LIMIT]


@router.get("/history/export")
def tarixce_ixrac(
    region: int = Query(..., description="Region id"),
    month: str | None = Query(default=None, description="YYYY-AA; boşdursa bütün satışlar"),
    user: User = Depends(OXUYAN),
):
    ay = ay_oxu(month) if month else None
    bugun = bu_gun()
    if ay and ay > bugun.replace(day=1):
        raise HTTPException(status_code=400, detail="Gələcək ay üçün məlumat yoxdur")
    bas = ay or date(2000, 1, 1)
    son = min(ay_son_gunu(ay), bugun) if ay else bugun
    with Session(engine) as session:
        region_ad = region_yoxla(session, region, user)
        noqteler = session.exec(
            select(Point)
            .where(Point.region_id == region, Point.active == True)  # noqa: E712
            .order_by(Point.novu, Point.ad, Point.id)
        ).all()
        dermanlar = session.exec(
            select(Medicine)
            .where(Medicine.active == True)  # noqa: E712
            .order_by(Medicine.id)
        ).all()
        noqtelerin_idleri = [p.id for p in noqteler]
        derman_idleri = [d.id for d in dermanlar]
        satislar = {
            (pid, mid): int(say)
            for pid, mid, say in session.exec(
                select(M.point_id, M.medicine_id, func.sum(M.say))
                .where(
                    M.point_id.in_(noqtelerin_idleri),
                    M.medicine_id.in_(derman_idleri),
                    M.user_id == user.id,
                    M.novu == "satis",
                    M.tarix >= bas,
                    M.tarix <= son,
                )
                .group_by(M.point_id, M.medicine_id)
            ).all()
        }
        qiymetler = {}
        for qiymet in session.exec(
            select(MedicinePrice)
            .where(
                MedicinePrice.medicine_id.in_(derman_idleri),
                MedicinePrice.baslama_tarixi <= son,
            )
            .order_by(MedicinePrice.baslama_tarixi.desc(), MedicinePrice.id.desc())
        ).all():
            qiymetler.setdefault(qiymet.medicine_id, qiymet.qiymet)

        kitab = Workbook()
        varag = kitab.active
        varag.title = "Satış"
        varag.sheet_view.rightToLeft = False
        varag.sheet_view.showGridLines = False
        say_sutunu = len(noqteler) + 2
        qiymet_sutunu = say_sutunu + 1
        cem_sutunu = say_sutunu + 2
        son_sutun = get_column_letter(cem_sutunu)
        varag.append([region_ad, f"Nümayəndə adı: {user.ad}"])
        basliq_sonu = len(noqteler) + 1 if noqteler else cem_sutunu
        if basliq_sonu > 2:
            varag.merge_cells(start_row=1, start_column=2, end_row=1, end_column=basliq_sonu)
        varag.append(["Dərman adı", *[p.ad for p in noqteler], "Say", "Qiymət", "Cəm"])
        cemi_say = 0
        cemi_pul = Decimal("0")
        qiymet_catismir = False
        for derman in dermanlar:
            saylar = [satislar.get((p.id, derman.id), 0) for p in noqteler]
            say = sum(saylar)
            qiymet = qiymetler.get(derman.id)
            cem = (qiymet * say).quantize(Decimal("0.01")) if qiymet is not None else None
            if say and qiymet is None:
                qiymet_catismir = True
            cemi_say += say
            cemi_pul += cem or Decimal("0")
            varag.append([
                derman.ad,
                *[s if s else None for s in saylar],
                say,
                float(qiymet) if qiymet is not None else None,
                float(cem) if cem is not None else (None if say else 0),
            ])
        son_derman_setri = varag.max_row
        varag.append(["Cəmi mal", *[None for _ in noqteler], cemi_say, None, None])
        varag.append(["Cəmi pul", *[None for _ in noqteler], None, None,
                      None if qiymet_catismir else float(cemi_pul)])
        ince = Side(style="thin", color="D5E3E7")
        serhed = Border(left=ince, right=ince, top=ince, bottom=ince)
        for setir in varag.iter_rows():
            for hucre in setir:
                if isinstance(hucre.value, str):
                    hucre.data_type = "s"
                hucre.font = Font(name="Calibri", size=10)
                hucre.border = serhed
                hucre.alignment = Alignment(
                    vertical="center", wrap_text=True,
                    horizontal="left" if hucre.column == 1 else "right",
                )
                if hucre.column in (qiymet_sutunu, cem_sutunu) and hucre.row > 2:
                    hucre.number_format = '#,##0.00'
        for setir in (1, 2):
            for hucre in varag[setir]:
                hucre.fill = PatternFill("solid", fgColor="0E7490")
                hucre.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
                hucre.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            varag.row_dimensions[setir].height = 32
        for setir in (son_derman_setri + 1, son_derman_setri + 2):
            for hucre in varag[setir]:
                hucre.fill = PatternFill("solid", fgColor="E2EFF0")
                hucre.font = Font(name="Calibri", size=11, bold=True, color="16313C")
        varag.column_dimensions["A"].width = 28
        for sutun in range(2, say_sutunu):
            varag.column_dimensions[get_column_letter(sutun)].width = 15
        for sutun, en in ((say_sutunu, 9), (qiymet_sutunu, 12), (cem_sutunu, 15)):
            varag.column_dimensions[get_column_letter(sutun)].width = en
        varag.freeze_panes = "B3"
        varag.auto_filter.ref = f"A2:{son_sutun}{son_derman_setri}"
        varag.sheet_properties.pageSetUpPr.fitToPage = True
        varag.page_setup.orientation = "landscape"
        varag.page_setup.paperSize = varag.PAPERSIZE_A4
        varag.page_setup.fitToWidth = 1
        varag.page_setup.fitToHeight = 0
        varag.print_title_rows = "1:2"
        varag.print_options.horizontalCentered = True
        varag.print_area = f"A1:{son_sutun}{varag.max_row}"

        bufer = io.BytesIO()
        kitab.save(bufer)
        kitab.close()
        bufer.seek(0)
        ay_hissesi = ay.strftime("%Y-%m") if ay else "butun"
        return StreamingResponse(
            bufer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="medstock-satis-{region}-{ay_hissesi}.xlsx"'
            },
        )


# ---------- Düzəliş / silmə (audit ilə) ----------


def audit_yaz(
    session: Session,
    entity: str,
    entity_id: int,
    action: str,
    user: User,
    evvelki: dict | None,
    sonraki: dict | None,
):
    session.add(
        RecordAudit(
            entity=entity,
            entity_id=entity_id,
            action=action,
            evvelki=json.dumps(evvelki, ensure_ascii=False) if evvelki else None,
            sonraki=json.dumps(sonraki, ensure_ascii=False) if sonraki else None,
            user_id=user.id,
        )
    )


def hereket_tap(session: Session, mid: int) -> M:
    hereket = session.get(M, mid)
    if not hereket:
        raise HTTPException(status_code=404, detail="Qeyd tapılmadı")
    return hereket


def resept_tap(session: Session, pid: int) -> Prescription:
    resept = session.get(Prescription, pid)
    if not resept:
        raise HTTPException(status_code=404, detail="Qeyd tapılmadı")
    return resept


def icazeni_yoxla(user: User, created_by: int | None):
    if not catma_icazesi_var(user, created_by):
        raise HTTPException(
            status_code=403, detail="Yalnız öz qeydlərini və ya menecer bütün qeydləri dəyişə bilər"
        )


def tarix_qaydasi(t: date) -> date:
    if t > bu_gun():
        raise HTTPException(status_code=422, detail="Gələcək tarix yazmaq olmaz")
    return t


class HereketDuzelis(BaseModel):
    say: int = Field(gt=0, le=1_000_000)
    tarix: date
    sebeb: str | None = Field(default=None, max_length=300)


class ReseptDuzelis(BaseModel):
    say: int = Field(gt=0, le=1_000_000)
    tarix: date


@router.patch("/movements/{mid}")
def hereket_duzelt(
    mid: int, data: HereketDuzelis, user: User = Depends(OXUYAN)
):
    tarix = tarix_qaydasi(data.tarix)
    with Session(engine) as session:
        hereket = hereket_tap(session, mid)
        icazeni_yoxla(user, hereket.created_by)
        evvelki = {
            "say": hereket.say,
            "tarix": hereket.tarix.isoformat(),
            "sebeb": hereket.sebeb,
        }
        hereket.say = data.say
        hereket.tarix = tarix
        hereket.sebeb = (data.sebeb or "").strip() or None
        audit_yaz(
            session, "movement", hereket.id, "update", user, evvelki, {
                "say": hereket.say,
                "tarix": hereket.tarix.isoformat(),
                "sebeb": hereket.sebeb,
            }
        )
        session.commit()
        return {"ok": True}


@router.delete("/movements/{mid}")
def hereket_sil(mid: int, user: User = Depends(OXUYAN)):
    with Session(engine) as session:
        hereket = hereket_tap(session, mid)
        icazeni_yoxla(user, hereket.created_by)
        audit_yaz(
            session,
            "movement",
            hereket.id,
            "delete",
            user,
            {
                "say": hereket.say,
                "tarix": hereket.tarix.isoformat(),
                "sebeb": hereket.sebeb,
            },
            None,
        )
        session.delete(hereket)
        session.commit()
        return {"ok": True}


@router.patch("/prescriptions/{pid}")
def resept_duzelt(
    pid: int, data: ReseptDuzelis, user: User = Depends(OXUYAN)
):
    tarix = tarix_qaydasi(data.tarix)
    with Session(engine) as session:
        resept = resept_tap(session, pid)
        icazeni_yoxla(user, resept.created_by)
        evvelki = {"say": resept.say, "tarix": resept.tarix.isoformat()}
        resept.say = data.say
        resept.tarix = tarix
        audit_yaz(
            session,
            "prescription",
            resept.id,
            "update",
            user,
            evvelki,
            {"say": resept.say, "tarix": resept.tarix.isoformat()},
        )
        session.commit()
        return {"ok": True}


@router.delete("/prescriptions/{pid}")
def resept_sil(pid: int, user: User = Depends(OXUYAN)):
    with Session(engine) as session:
        resept = resept_tap(session, pid)
        icazeni_yoxla(user, resept.created_by)
        audit_yaz(
            session,
            "prescription",
            resept.id,
            "delete",
            user,
            {"say": resept.say, "tarix": resept.tarix.isoformat()},
            None,
        )
        session.delete(resept)
        session.commit()
        return {"ok": True}


@router.get("/history/audit")
def audit_tarixce(
    entity: str = Query(..., description="movement və ya prescription"),
    entity_id: int = Query(...),
    user: User = Depends(OXUYAN),
):
    if entity not in ("movement", "prescription"):
        raise HTTPException(status_code=422, detail="Entity düzgün deyil")
    with Session(engine) as session:
        setirler = session.exec(
            select(RecordAudit, User)
            .outerjoin(User, RecordAudit.user_id == User.id)
            .where(RecordAudit.entity == entity, RecordAudit.entity_id == entity_id)
            .order_by(RecordAudit.created_at.desc())
        ).all()
        return [
            {
                "action": a.action,
                "evvelki": json.loads(a.evvelki) if a.evvelki else None,
                "sonraki": json.loads(a.sonraki) if a.sonraki else None,
                "user_ad": u.ad if u else None,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a, u in setirler
        ]
