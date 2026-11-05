from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from auth import rol_teleb_et
from database import engine
from models import Medicine, MedicinePrice, User
from routes_stock import bu_gun

router = APIRouter()
OXUYAN = rol_teleb_et("representative", "manager")
MENECER = rol_teleb_et("manager")


def qiymet_json(p: MedicinePrice, adlar: dict[int, str]) -> dict:
    return {
        "id": p.id,
        "qiymet": float(p.qiymet),
        "baslama_tarixi": p.baslama_tarixi.isoformat(),
        "kim": adlar.get(p.created_by) if p.created_by else None,
    }


@router.get("/prices")
def qiymetler(user: User = Depends(OXUYAN)):
    bugun = bu_gun()
    with Session(engine) as session:
        dermanlar = session.exec(
            select(Medicine).where(Medicine.active == True).order_by(Medicine.id)  # noqa: E712
        ).all()
        butun = session.exec(
            select(MedicinePrice).order_by(
                MedicinePrice.baslama_tarixi.desc(), MedicinePrice.id.desc()
            )
        ).all()
        adlar = {u.id: u.ad for u in session.exec(select(User)).all()}

        netice = []
        for d in dermanlar:
            tarixce = [p for p in butun if p.medicine_id == d.id]
            cari = next((p for p in tarixce if p.baslama_tarixi <= bugun), None)
            netice.append(
                {
                    "medicine_id": d.id,
                    "ad": d.ad,
                    "cari": qiymet_json(cari, adlar) if cari else None,
                    "tarixce": [qiymet_json(p, adlar) for p in tarixce],
                }
            )
        return {"dermanlar": netice}


class QiymetGiris(BaseModel):
    medicine_id: int
    qiymet: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    baslama_tarixi: date | None = None  # boşdursa bu gün


@router.post("/prices")
def qiymet_elave_et(data: QiymetGiris, user: User = Depends(MENECER)):
    bugun = bu_gun()
    tarix = data.baslama_tarixi or bugun
    if tarix < bugun:
        raise HTTPException(
            status_code=400, detail="Qüvvəyə minmə tarixi keçmiş ola bilməz"
        )
    with Session(engine) as session:
        derman = session.get(Medicine, data.medicine_id)
        if not derman or not derman.active:
            raise HTTPException(status_code=404, detail="Dərman tapılmadı")
        yeni = MedicinePrice(
            medicine_id=derman.id,
            qiymet=data.qiymet,
            baslama_tarixi=tarix,
            created_by=user.id,
        )
        session.add(yeni)
        session.commit()
        session.refresh(yeni)
        return {
            "id": yeni.id,
            "medicine_id": derman.id,
            "ad": derman.ad,
            "qiymet": float(yeni.qiymet),
            "baslama_tarixi": yeni.baslama_tarixi.isoformat(),
        }