from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, select

from auth import rol_teleb_et
from database import engine
from models import Clinic, Doctor, Medicine, MonthlyReport, MonthlyReportRow, User
from routes_reference import istifadeci_regionlari
from routes_reports import ay_oxu, bu_ay

router = APIRouter()
OXUYAN = rol_teleb_et("representative", "manager")
GORUNEN_STATUSLAR = ("gonderildi", "tesdiqlendi")
CEM = func.sum(MonthlyReportRow.say)


def ay_cix(d: date, n: int) -> date:
    """d ayından n ay əvvəlki ayın birinci günü."""
    toplam = d.year * 12 + (d.month - 1) - n
    return date(toplam // 12, toplam % 12 + 1, 1)


def baza(sutunlar, user: User, region_idleri: list[int], ay_min: date, ay_max: date):
    """Bütün cəmlər üçün ortaq sorğu: kimin hesabatları, hansı aylar, hansı regionlar."""
    sorgu = (
        select(*sutunlar)
        .select_from(MonthlyReportRow)
        .join(MonthlyReport, MonthlyReportRow.report_id == MonthlyReport.id)
        .join(Doctor, MonthlyReportRow.doctor_id == Doctor.id)
        .join(Clinic, Doctor.clinic_id == Clinic.id)
        .where(
            MonthlyReport.ay >= ay_min,
            MonthlyReport.ay <= ay_max,
            Clinic.region_id.in_(region_idleri),
        )
    )
    if user.rol == "representative":
        return sorgu.where(MonthlyReport.user_id == user.id)
    # Menecer: yalnız ona bağlı işçilərin göndərilmiş/təsdiqlənmiş hesabatları
    return sorgu.where(
        MonthlyReport.status.in_(GORUNEN_STATUSLAR),
        MonthlyReport.user_id.in_(select(User.id).where(User.manager_id == user.id)),
    )


@router.get("/reports/summary")
def xulase(
    month: str | None = Query(default=None, description="YYYY-AA; boşdursa cari ay"),
    region: int | None = Query(default=None, description="Region id; boşdursa hamısı"),
    user: User = Depends(OXUYAN),
):
    ay = ay_oxu(month) if month else bu_ay()
    if ay > bu_ay():
        raise HTTPException(status_code=400, detail="Gələcək ay üçün məlumat yoxdur")
    evvelki = ay_cix(ay, 1)
    ay_min = ay_cix(ay, 5)

    with Session(engine) as session:
        icazeli = istifadeci_regionlari(session, user)
        if region is not None and region not in icazeli:
            raise HTTPException(status_code=403, detail="Bu region sənə təyin olunmayıb")
        region_idleri = [region] if region is not None else list(icazeli)
        region_idleri = region_idleri or [-1]  # regionu yoxdursa heç nə tapılmasın

        # 1) Son 6 ayın ümumi cəmi
        aylar = dict(
            session.exec(
                baza([MonthlyReport.ay, CEM], user, region_idleri, ay_min, ay).group_by(
                    MonthlyReport.ay
                )
            ).all()
        )
        son_6_ay = [
            {"ay": a.strftime("%Y-%m"), "cemi": int(aylar.get(a, 0))}
            for a in (ay_cix(ay, i) for i in range(5, -1, -1))
        ]

        # 2) Dərman üzrə: bu ay və keçən ay
        derman_neticesi = session.exec(
            baza(
                [MonthlyReport.ay, MonthlyReportRow.medicine_id, CEM],
                user,
                region_idleri,
                evvelki,
                ay,
            ).group_by(MonthlyReport.ay, MonthlyReportRow.medicine_id)
        ).all()
        cari_derman = {m: int(s) for a, m, s in derman_neticesi if a == ay}
        evvel_derman = {m: int(s) for a, m, s in derman_neticesi if a == evvelki}

        butun_dermanlar = session.exec(select(Medicine).order_by(Medicine.id)).all()
        dermanlar = []
        for sira, d in enumerate(butun_dermanlar):  # sira /medicines ilə eynidir
            cemi = cari_derman.get(d.id, 0)
            evvel = evvel_derman.get(d.id, 0)
            if not d.active and cemi == 0 and evvel == 0:
                continue
            faiz = round((cemi - evvel) / evvel * 100, 1) if evvel > 0 else None
            dermanlar.append(
                {
                    "id": d.id,
                    "ad": d.ad,
                    "sira": sira,
                    "cemi": cemi,
                    "evvelki_ay": evvel,
                    "ferq_faiz": faiz,
                }
            )

        # 3) Həkimlər üzrə (bu ay), dərmanlara bölünmüş
        hekim_neticesi = session.exec(
            baza(
                [MonthlyReportRow.doctor_id, MonthlyReportRow.medicine_id, CEM],
                user,
                region_idleri,
                ay,
                ay,
            ).group_by(MonthlyReportRow.doctor_id, MonthlyReportRow.medicine_id)
        ).all()
        hekim_cemleri: dict[int, dict[int, int]] = {}
        for hekim_id, derman_id, say in hekim_neticesi:
            hekim_cemleri.setdefault(hekim_id, {})[derman_id] = int(say)
        hekim_adlari = {}
        if hekim_cemleri:
            hekim_adlari = dict(
                session.exec(
                    select(Doctor.id, Doctor.ad).where(Doctor.id.in_(list(hekim_cemleri)))
                ).all()
            )
        hekimler = sorted(
            (
                {
                    "id": hid,
                    "ad": hekim_adlari.get(hid, "?"),
                    "cemi": sum(dm.values()),
                    "dermanlar": [
                        {"medicine_id": m, "say": s} for m, s in sorted(dm.items())
                    ],
                }
                for hid, dm in hekim_cemleri.items()
            ),
            key=lambda x: (-x["cemi"], x["ad"]),
        )

        cavab = {
            "ay": ay.strftime("%Y-%m"),
            "region_id": region,
            "cemi": int(aylar.get(ay, 0)),
            "evvelki_cemi": int(aylar.get(evvelki, 0)),
            "dermanlar": dermanlar,
            "hekimler": hekimler,
            "son_6_ay": son_6_ay,
        }

        # 4) Menecer üçün əlavə: işçilər və regionlar üzrə
        if user.rol == "manager":
            isci_neticesi = dict(
                session.exec(
                    baza([MonthlyReport.user_id, CEM], user, region_idleri, ay, ay).group_by(
                        MonthlyReport.user_id
                    )
                ).all()
            )
            isci_adlari = {}
            if isci_neticesi:
                isci_adlari = dict(
                    session.exec(
                        select(User.id, User.ad).where(User.id.in_(list(isci_neticesi)))
                    ).all()
                )
            region_neticesi = dict(
                session.exec(
                    baza([Clinic.region_id, CEM], user, region_idleri, ay, ay).group_by(
                        Clinic.region_id
                    )
                ).all()
            )
            cavab["iscilar"] = sorted(
                (
                    {"id": uid, "ad": isci_adlari.get(uid, "?"), "cemi": int(c)}
                    for uid, c in isci_neticesi.items()
                ),
                key=lambda x: -x["cemi"],
            )
            cavab["regionlar"] = sorted(
                (
                    {"id": rid, "ad": icazeli.get(rid, "?"), "cemi": int(c)}
                    for rid, c in region_neticesi.items()
                ),
                key=lambda x: -x["cemi"],
            )

        return cavab