from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func
from sqlmodel import Session, select

from auth import cari_user, rol_teleb_et
from database import engine
from models import Medicine, Notification, Point, StockMovement, StockRequest, StockRequestRow, User
from routes_reference import istifadeci_regionlari
from routes_stock import asagi_hedd, bu_gun, derman_yoxla, nokte_yoxla, qaliq_ifadesi, status_tap

router = APIRouter()
NUMAYENDE = rol_teleb_et("representative")
MENECER = rol_teleb_et("manager")
OXUYAN = rol_teleb_et("representative", "manager")


class TalebSetri(BaseModel):
    point_id: int
    medicine_id: int
    say: int = Field(strict=True, gt=0, le=100000)


class TalebGiris(BaseModel):
    setirler: list[TalebSetri] = Field(max_length=100)


class QerarGiris(BaseModel):
    status: Literal["tesdiqlendi", "gozleyir"]
    serh: str | None = Field(default=None, max_length=500)


def secimler(session: Session, user: User) -> dict:
    regionlar = istifadeci_regionlari(session, user)
    noqteler = session.exec(
        select(Point).where(Point.region_id.in_(list(regionlar)), Point.active == True).order_by(Point.ad)
    ).all()
    dermanlar = session.exec(select(Medicine).order_by(Medicine.id)).all()
    idler = [p.id for p in noqteler]
    qaliqlar = dict(
        ((pid, mid), int(q))
        for pid, mid, q in session.exec(
            select(StockMovement.point_id, StockMovement.medicine_id, qaliq_ifadesi())
            .where(StockMovement.point_id.in_(idler), StockMovement.tarix <= bu_gun())
            .group_by(StockMovement.point_id, StockMovement.medicine_id)
        ).all()
    )
    hedd = asagi_hedd(session)
    items = []
    for p in noqteler:
        for sira, d in enumerate(dermanlar):
            if not d.active:
                continue
            qaliq = qaliqlar.get((p.id, d.id), 0)
            status = status_tap(qaliq, hedd)
            if status != "normal":
                items.append({"point_id": p.id, "point_ad": p.ad, "region_ad": regionlar[p.region_id],
                              "medicine_id": d.id, "medicine_ad": d.ad, "sira": sira,
                              "qaliq": qaliq, "status": status})
    manager = session.get(User, user.manager_id) if user.manager_id else None
    return {
        "manager_ad": manager.ad if manager and manager.active and manager.rol == "manager" else None,
        "items": sorted(items, key=lambda i: (i["qaliq"], i["medicine_ad"], i["point_ad"])),
        "pharmacies": [{"id": p.id, "ad": p.ad, "region_ad": regionlar[p.region_id]} for p in noqteler if p.novu == "aptek"],
        "medicines": [{"id": d.id, "ad": d.ad, "sira": s} for s, d in enumerate(dermanlar) if d.active],
    }


def taleb_tap(session: Session, taleb_id: int, user: User) -> StockRequest:
    taleb = session.exec(select(StockRequest).where(StockRequest.id == taleb_id).with_for_update()).first()
    if not taleb:
        raise HTTPException(404, "Stok tələbi tapılmadı")
    sahib = session.get(User, taleb.user_id)
    if user.rol == "representative" and taleb.user_id == user.id:
        return taleb
    if user.rol == "manager" and sahib.manager_id == user.id and taleb.status != "qaralama":
        return taleb
    raise HTTPException(403, "Bu stok tələbi üçün icazən yoxdur")


def taleb_cavabi(session: Session, taleb: StockRequest) -> dict:
    dermanlar = session.exec(select(Medicine.id).order_by(Medicine.id)).all()
    siralar = {mid: i for i, mid in enumerate(dermanlar)}
    setirler = session.exec(
        select(StockRequestRow, Point, Medicine)
        .join(Point, StockRequestRow.point_id == Point.id)
        .join(Medicine, StockRequestRow.medicine_id == Medicine.id)
        .where(StockRequestRow.request_id == taleb.id).order_by(Point.ad, Medicine.id)
    ).all()
    return {
        "id": taleb.id, "user_ad": session.get(User, taleb.user_id).ad,
        "status": taleb.status, "menecer_serhi": taleb.menecer_serhi,
        "created_at": taleb.created_at.isoformat(),
        "setirler": [{"point_id": p.id, "point_ad": p.ad, "medicine_id": d.id,
                      "medicine_ad": d.ad, "sira": siralar[d.id], "say": r.say} for r, p, d in setirler],
    }


def setirleri_yoxla(session: Session, setirler: list[TalebSetri], user: User):
    cutler = [(s.point_id, s.medicine_id) for s in setirler]
    if len(set(cutler)) != len(cutler):
        raise HTTPException(422, "Eyni aptek və dərman təkrarlanır")
    az_dermanlar = {i["medicine_id"] for i in secimler(session, user)["items"]}
    for s in setirler:
        p = nokte_yoxla(session, s.point_id, user)
        if p.novu != "aptek":
            raise HTTPException(422, "Stok tələbi üçün aptek seçin")
        derman_yoxla(session, s.medicine_id)
        if s.medicine_id not in az_dermanlar:
            raise HTTPException(409, "Bu dərman artıq diqqət tələb etmir")


@router.get("/stock-requests/options")
def taleb_secimleri(user: User = Depends(NUMAYENDE)):
    with Session(engine) as session:
        return secimler(session, user)


@router.get("/stock-requests")
def talebler(user: User = Depends(OXUYAN)):
    with Session(engine) as session:
        sorgu = select(StockRequest)
        if user.rol == "representative":
            sorgu = sorgu.where(StockRequest.user_id == user.id)
        else:
            sorgu = sorgu.join(User, StockRequest.user_id == User.id).where(
                User.manager_id == user.id, StockRequest.status != "qaralama")
        return [taleb_cavabi(session, h) for h in session.exec(sorgu.order_by(StockRequest.id.desc())).all()]


@router.post("/stock-requests")
def taleb_yarat(data: TalebGiris, user: User = Depends(NUMAYENDE)):
    with Session(engine) as session:
        setirleri_yoxla(session, data.setirler, user)
        taleb = StockRequest(user_id=user.id)
        session.add(taleb)
        session.flush()
        for s in data.setirler:
            session.add(StockRequestRow(request_id=taleb.id, **s.model_dump()))
        session.commit()
        session.refresh(taleb)
        return taleb_cavabi(session, taleb)


@router.get("/stock-requests/{taleb_id}")
def taleb_detali(taleb_id: int, user: User = Depends(OXUYAN)):
    with Session(engine) as session:
        return taleb_cavabi(session, taleb_tap(session, taleb_id, user))


@router.put("/stock-requests/{taleb_id}")
def taleb_saxla(taleb_id: int, data: TalebGiris, user: User = Depends(NUMAYENDE)):
    with Session(engine) as session:
        taleb = taleb_tap(session, taleb_id, user)
        if taleb.status != "qaralama":
            raise HTTPException(409, "Göndərilmiş stok tələbi dəyişdirilə bilməz")
        setirleri_yoxla(session, data.setirler, user)
        session.execute(delete(StockRequestRow).where(StockRequestRow.request_id == taleb.id))
        for s in data.setirler:
            session.add(StockRequestRow(request_id=taleb.id, **s.model_dump()))
        session.commit()
        return taleb_cavabi(session, taleb)


@router.post("/stock-requests/{taleb_id}/submit")
def taleb_gonder(taleb_id: int, user: User = Depends(NUMAYENDE)):
    with Session(engine) as session:
        taleb = taleb_tap(session, taleb_id, user)
        if taleb.status != "qaralama":
            raise HTTPException(409, "Stok tələbi artıq göndərilib")
        manager = session.get(User, user.manager_id) if user.manager_id else None
        if not manager or not manager.active or manager.rol != "manager":
            raise HTTPException(409, "Aktiv menecer təyin olunmayıb")
        setirler = session.exec(select(StockRequestRow).where(StockRequestRow.request_id == taleb.id)).all()
        if not setirler:
            raise HTTPException(422, "Boş stok tələbi göndərilə bilməz")
        setirleri_yoxla(session, [TalebSetri(point_id=s.point_id, medicine_id=s.medicine_id, say=s.say) for s in setirler], user)
        taleb.status = "gonderildi"
        session.add(taleb)
        session.add(Notification(user_id=manager.id, request_id=taleb.id, kind="submitted"))
        session.commit()
        return taleb_cavabi(session, taleb)


@router.post(
    "/stock-requests/{taleb_id}/decision",
    description="Approval records incoming stock at each selected pharmacy in the same transaction as the decision. Holding does not change stock.",
)
def taleb_qerari(taleb_id: int, data: QerarGiris, user: User = Depends(MENECER)):
    with Session(engine) as session:
        taleb = taleb_tap(session, taleb_id, user)
        if taleb.status not in ("gonderildi", "gozleyir") or data.status == taleb.status:
            raise HTTPException(409, "Bu stok tələbi üçün qərar artıq verilib")
        if data.status == "tesdiqlendi":
            sahib = session.get(User, taleb.user_id)
            tarix = bu_gun()
            setirler = session.exec(select(StockRequestRow).where(StockRequestRow.request_id == taleb.id).order_by(StockRequestRow.id)).all()
            for s in setirler:
                p = nokte_yoxla(session, s.point_id, sahib)
                if p.novu != "aptek":
                    raise HTTPException(422, "Stok tələbi üçün aptek seçin")
                derman_yoxla(session, s.medicine_id)
                session.add(StockMovement(
                    point_id=p.id, medicine_id=s.medicine_id, user_id=user.id,
                    novu="daxilolma", say=s.say, tarix=tarix,
                    sebeb=f"Stok tələbi #{taleb.id}", created_by=user.id,
                ))
        taleb.status = data.status
        taleb.menecer_serhi = (data.serh or "").strip() or None
        session.add(taleb)
        session.add(Notification(user_id=taleb.user_id, request_id=taleb.id, kind=data.status))
        for b in session.exec(select(Notification).where(Notification.user_id == user.id, Notification.request_id == taleb.id)).all():
            b.read = True
            session.add(b)
        session.commit()
        return taleb_cavabi(session, taleb)


def bildiris_sorgusu(user: User):
    sorgu = select(Notification).join(StockRequest, Notification.request_id == StockRequest.id).join(User, StockRequest.user_id == User.id).where(
        Notification.user_id == user.id, StockRequest.status != "qaralama")
    if user.rol == "manager":
        return sorgu.where(User.manager_id == user.id)
    return sorgu.where(StockRequest.user_id == user.id)


@router.get("/notifications")
def bildirisler(user: User = Depends(cari_user)):
    with Session(engine) as session:
        sorgu = bildiris_sorgusu(user)
        unread = session.exec(select(func.count()).select_from(sorgu.where(Notification.read == False).subquery())).one()
        items = []
        for b in session.exec(sorgu.order_by(Notification.id.desc()).limit(100)).all():
            taleb = session.get(StockRequest, b.request_id)
            sahib = session.get(User, taleb.user_id)
            manager = session.get(User, sahib.manager_id) if sahib.manager_id else None
            items.append({"id": b.id, "request_id": b.request_id, "kind": b.kind,
                          "user_ad": sahib.ad if b.kind == "submitted" else (manager.ad if manager else ""),
                          "created_at": b.created_at.isoformat(), "read": b.read})
        return {"unread": unread, "items": items}


@router.post("/notifications/{bildiris_id}/read")
def bildiris_oxu(bildiris_id: int, user: User = Depends(cari_user)):
    with Session(engine) as session:
        b = session.exec(bildiris_sorgusu(user).where(Notification.id == bildiris_id)).first()
        if not b:
            raise HTTPException(404, "Bildiriş tapılmadı")
        b.read = True
        session.add(b)
        session.commit()
        return {"id": b.id, "read": True}
