import getpass

from sqlmodel import Session, select

from database import engine
from models import Clinic, Doctor, Medicine, Point, Region, User, UserRegion
from security import parol_hashle


def tap_ve_ya_yarat(session, model, where: dict, defaults: dict | None = None):
    sorgu = select(model)
    for sahe, deyer in where.items():
        sorgu = sorgu.where(getattr(model, sahe) == deyer)
    obyekt = session.exec(sorgu).first()
    if obyekt:
        return obyekt
    obyekt = model(**where, **(defaults or {}))
    session.add(obyekt)
    session.flush()
    return obyekt


def say(session, model) -> int:
    return len(session.exec(select(model)).all())


with Session(engine) as s:
    # Regionlar
    regionlar = {
        ad: tap_ve_ya_yarat(s, Region, {"ad": ad})
        for ad in ["Qəbələ", "İsmayıllı", "Şamaxı"]
    }

    # Dərmanlar
    for ad in ["Dərman A", "Dərman B", "Dərman C"]:
        tap_ve_ya_yarat(s, Medicine, {"ad": ad})

    # Klinikalar
    klinika1 = tap_ve_ya_yarat(
        s, Clinic, {"ad": "Qəbələ Klinikası", "region_id": regionlar["Qəbələ"].id}
    )
    klinika2 = tap_ve_ya_yarat(
        s, Clinic, {"ad": "Şamaxı Klinikası", "region_id": regionlar["Şamaxı"].id}
    )

    # Həkimlər
    for ad, ixtisas, klinika in [
        ("Həkim 1", "Terapevt", klinika1),
        ("Həkim 2", "Kardioloq", klinika1),
        ("Həkim 3", "Nevroloq", klinika2),
        ("Həkim 4", "Pediatr", klinika2),
    ]:
        tap_ve_ya_yarat(
            s, Doctor, {"ad": ad, "clinic_id": klinika.id}, {"ixtisas": ixtisas}
        )

    # Aptek və depolar
    for ad, novu, region in [
        ("Aptek 1", "aptek", "Qəbələ"),
        ("Depo 1", "depo", "Qəbələ"),
        ("Aptek 2", "aptek", "Şamaxı"),
    ]:
        tap_ve_ya_yarat(
            s, Point, {"ad": ad, "region_id": regionlar[region].id}, {"novu": novu}
        )

    # İstifadəçilər
    menecer = tap_ve_ya_yarat(
        s,
        User,
        {"login": "menecer1"},
        {"ad": "Test Menecer", "rol": "manager", "parol_hash": parol_hashle("Test-Menecer-1")},
    )
    numayende = tap_ve_ya_yarat(
        s,
        User,
        {"login": "numayende1"},
        {
            "ad": "Test Nümayəndə",
            "rol": "representative",
            "parol_hash": parol_hashle("Test-Numayende-1"),
            "manager_id": menecer.id,
        },
    )
    if numayende.manager_id is None:
        numayende.manager_id = menecer.id

    admin = s.exec(select(User).where(User.login == "admin")).first()
    if not admin:
        while True:
            parol = getpass.getpass("Admin şifrəsi (ən azı 12 simvol): ")
            if len(parol) >= 12:
                break
            print("Şifrə çox qısadır.")
        s.add(User(login="admin", ad="Admin", rol="admin", parol_hash=parol_hashle(parol)))

    # İstifadəçi və region bağlantıları
    for istifadeci, adlar in [
        (numayende, ["Qəbələ", "Şamaxı"]),
        (menecer, ["Qəbələ", "İsmayıllı", "Şamaxı"]),
    ]:
        for ad in adlar:
            tap_ve_ya_yarat(
                s,
                UserRegion,
                {"user_id": istifadeci.id, "region_id": regionlar[ad].id},
            )

    s.commit()

    print("Hazırdır.")
    print("Regionlar:", say(s, Region))
    print("Dərmanlar:", say(s, Medicine))
    print("Klinikalar:", say(s, Clinic))
    print("Həkimlər:", say(s, Doctor))
    print("Aptek/depolar:", say(s, Point))
    print("İstifadəçilər:", say(s, User))