import calendar
import io
import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from auth import rol_teleb_et
from database import engine
from models import (
    Doctor,
    Medicine,
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
    month: str | None = Query(default=None, description="YYYY-AA; boşdursa bütün tarixçə"),
    user: User = Depends(OXUYAN),
):
    ay = ay_oxu(month) if month else None
    with Session(engine) as session:
        region_ad = region_yoxla(session, region, user)
        kartlar = tarixce_sorgula(session, region, None, ay)

        kitab = Workbook()
        varag = kitab.active
        varag.title = "Qeydlər"
        varag.sheet_view.rightToLeft = False

        basliq_reng = PatternFill("solid", fgColor="0E7490")
        basliq_yazi = Font(bold=True, color="FFFFFF")
        varag.append(
            [
                f"{region_ad} · "
                + (ay.strftime("%Y-%m") if ay else "bütün tarixçə")
                + f" · {len(kartlar)} qeyd"
            ]
        )
        varag["A1"].font = Font(bold=True, size=12)
        varag["A1"].data_type = "s"
        varag.append([])
        varag.merge_cells("A1:G1")
        sutunlar = ["Tarix", "Növ", "Dərman", "Məntəqə", "Say", "Qeyd/Həkim", "İşçi"]
        varag.append(sutunlar)
        for hucre in varag[3]:
            hucre.fill = basliq_reng
            hucre.font = basliq_yazi
            hucre.alignment = Alignment(horizontal="center")

        for k in kartlar:
            varag.append(
                [
                    k["tarix"],
                    NOVLAR.get(k["novu"], k["novu"]),
                    k["derman"],
                    k["point_ad"],
                    k["say"],
                    k["sebeb"] or k.get("hekim") or "",
                    k["user_ad"] or "",
                ]
            )
        varag.freeze_panes = "A4"
        varag.auto_filter.ref = f"A3:G{varag.max_row}"
        varag.sheet_properties.pageSetUpPr.fitToPage = True
        varag.page_setup.orientation = "landscape"
        varag.page_setup.paperSize = varag.PAPERSIZE_A4
        varag.page_setup.fitToWidth = 1
        varag.page_setup.fitToHeight = 0
        varag.print_title_rows = "1:3"
        varag.print_options.horizontalCentered = True
        varag.print_area = f"A1:G{varag.max_row}"
        for setir in varag.iter_rows(min_row=4):
            for hucre in setir:
                if hucre.data_type == "f":
                    hucre.data_type = "s"
                hucre.font = Font(size=10)
                hucre.alignment = Alignment(
                    vertical="top", wrap_text=True,
                    horizontal="right" if hucre.column == 5 else "left",
                )
        enler = [12, 14, 18, 18, 6, 20, 16]
        for i, en in enumerate(enler, start=1):
            varag.column_dimensions[
                chr(ord("A") + i - 1)
            ].width = en

        bufer = io.BytesIO()
        kitab.save(bufer)
        bufer.seek(0)
        ay_hissesi = ay.strftime("%Y-%m") if ay else "butun"
        return StreamingResponse(
            bufer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="medstock-qeydler-{region}-{ay_hissesi}.xlsx"'
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
