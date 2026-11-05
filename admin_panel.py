from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqlmodel import Session, select
from starlette.requests import Request
from wtforms import PasswordField, SelectField

from auth import GIZLI_ACAR
from database import engine
from models import (
    Clinic,
    Doctor,
    Medicine,
    MedicinePrice,
    Point,
    Region,
    Setting,
    StockMovement,
    User,
    UserRegion,
)
from security import parol_hashle, parol_yoxla


class AdminAuth(AuthenticationBackend):
    """Yalnız aktiv admin roluna giriş icazəsi verir."""

    async def login(self, request: Request) -> bool:
        form = await request.form()
        login = str(form.get("username", "")).strip()
        parol = str(form.get("password", ""))
        with Session(engine) as session:
            user = session.exec(select(User).where(User.login == login)).first()
            if (
                user
                and user.active
                and user.rol == "admin"
                and parol_yoxla(parol, user.parol_hash)
            ):
                request.session.update({"admin_id": user.id})
                return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        admin_id = request.session.get("admin_id")
        if not admin_id:
            return False
        with Session(engine) as session:
            user = session.get(User, admin_id)
            return bool(user and user.active and user.rol == "admin")


def kim_yaratdi(model, is_created: bool, request: Request) -> None:
    """Yeni qeydlərdə 'kim yaratdı' sahəsini doldurur."""
    if is_created:
        model.created_by = request.session.get("admin_id")


class IzMixin:
    """Bütün bölmələrdə created_by sahəsini avtomatik doldurur."""

    async def on_model_change(self, data, model, is_created, request) -> None:
        kim_yaratdi(model, is_created, request)


class UserAdmin(ModelView, model=User):
    name = "İstifadəçi"
    name_plural = "İstifadəçilər"
    icon = "fa-solid fa-user"

    can_delete = False  # silmək əvəzinə "Aktiv" işarəsi götürülür

    column_list = [User.id, User.login, User.ad, User.rol, User.manager, User.active]
    column_searchable_list = [User.login, User.ad]
    column_labels = {
        User.login: "Login",
        User.ad: "Ad",
        User.rol: "Rol",
        User.manager: "Menecer",
        User.parol_hash: "Şifrə",
        User.active: "Aktiv",
    }

    form_columns = [
        User.login,
        User.ad,
        User.rol,
        User.manager,
        User.parol_hash,
        User.active,
    ]
    # Şifrə sahəsi gizli yazılır və mövcud dəyər heç vaxt göstərilmir
    form_overrides = {"parol_hash": PasswordField, "rol": SelectField}
    form_args = {
        "rol": {
            "choices": [
                ("admin", "Admin"),
                ("manager", "Menecer"),
                ("representative", "Tibbi nümayəndə"),
            ]
        }
    }

    async def on_model_change(self, data, model, is_created, request) -> None:
        parol = (data.get("parol_hash") or "").strip()
        if parol:
            if len(parol) < 8:
                raise ValueError("Şifrə ən azı 8 simvol olmalıdır")
            data["parol_hash"] = parol_hashle(parol)
        elif is_created:
            raise ValueError("Yeni istifadəçi üçün şifrə tələb olunur")
        else:
            data.pop("parol_hash", None)  # boş buraxılıb: şifrə dəyişmir
        kim_yaratdi(model, is_created, request)


class RegionAdmin(IzMixin, ModelView, model=Region):
    name = "Region"
    name_plural = "Regionlar"
    icon = "fa-solid fa-map-location-dot"

    can_delete = False

    column_list = [Region.id, Region.ad, Region.active]
    column_searchable_list = [Region.ad]
    column_labels = {Region.ad: "Ad", Region.active: "Aktiv"}
    form_columns = [Region.ad, Region.active]


class UserRegionAdmin(IzMixin, ModelView, model=UserRegion):
    name = "İstifadəçi–Region"
    name_plural = "İstifadəçi–Region bağlantıları"
    icon = "fa-solid fa-link"

    can_edit = False  # bağlantını dəyişmək əvəzinə silib yenisini əlavə et

    column_list = [UserRegion.user, UserRegion.region]
    column_labels = {UserRegion.user: "İstifadəçi", UserRegion.region: "Region"}
    form_columns = [UserRegion.user, UserRegion.region]


class ClinicAdmin(IzMixin, ModelView, model=Clinic):
    name = "Klinika"
    name_plural = "Klinikalar"
    icon = "fa-solid fa-hospital"

    can_delete = False

    column_list = [Clinic.id, Clinic.ad, Clinic.region, Clinic.unvan, Clinic.active]
    column_searchable_list = [Clinic.ad]
    column_labels = {
        Clinic.ad: "Ad",
        Clinic.region: "Region",
        Clinic.unvan: "Ünvan",
        Clinic.active: "Aktiv",
    }
    form_columns = [Clinic.ad, Clinic.region, Clinic.unvan, Clinic.active]


class DoctorAdmin(IzMixin, ModelView, model=Doctor):
    name = "Həkim"
    name_plural = "Həkimlər"
    icon = "fa-solid fa-user-doctor"

    can_delete = False

    column_list = [
        Doctor.id,
        Doctor.ad,
        Doctor.ixtisas,
        Doctor.clinic,
        Doctor.telefon,
        Doctor.active,
    ]
    column_searchable_list = [Doctor.ad]
    column_labels = {
        Doctor.ad: "Ad",
        Doctor.ixtisas: "İxtisas",
        Doctor.clinic: "Klinika",
        Doctor.telefon: "Telefon",
        Doctor.active: "Aktiv",
    }
    form_columns = [
        Doctor.ad,
        Doctor.ixtisas,
        Doctor.clinic,
        Doctor.telefon,
        Doctor.active,
    ]


class PointAdmin(IzMixin, ModelView, model=Point):
    name = "Aptek/depo"
    name_plural = "Aptek və depolar"
    icon = "fa-solid fa-store"

    can_delete = False

    column_list = [Point.id, Point.ad, Point.novu, Point.region, Point.unvan, Point.active]
    column_searchable_list = [Point.ad]
    column_labels = {
        Point.ad: "Ad",
        Point.novu: "Növ",
        Point.region: "Region",
        Point.unvan: "Ünvan",
        Point.active: "Aktiv",
    }
    form_columns = [Point.ad, Point.novu, Point.region, Point.unvan, Point.active]
    form_overrides = {"novu": SelectField}
    form_args = {"novu": {"choices": [("aptek", "Aptek"), ("depo", "Depo")]}}


class MedicineAdmin(IzMixin, ModelView, model=Medicine):
    name = "Dərman"
    name_plural = "Dərmanlar"
    icon = "fa-solid fa-pills"

    can_delete = False

    column_list = [Medicine.id, Medicine.ad, Medicine.forma, Medicine.active]
    column_searchable_list = [Medicine.ad]
    column_labels = {
        Medicine.ad: "Ad",
        Medicine.forma: "Forma",
        Medicine.active: "Aktiv",
    }
    form_columns = [Medicine.ad, Medicine.forma, Medicine.active]


class MedicinePriceAdmin(IzMixin, ModelView, model=MedicinePrice):
    name = "Qiymət"
    name_plural = "Qiymətlər"
    icon = "fa-solid fa-tag"

    # Qiymət dəyişəndə köhnə sətir silinmir, yeni sətir əlavə olunur
    can_edit = False
    can_delete = False

    column_list = [
        MedicinePrice.medicine,
        MedicinePrice.qiymet,
        MedicinePrice.baslama_tarixi,
        MedicinePrice.created_at,
    ]
    column_labels = {
        MedicinePrice.medicine: "Dərman",
        MedicinePrice.qiymet: "Qiymət",
        MedicinePrice.baslama_tarixi: "Qüvvəyə minmə tarixi",
        MedicinePrice.created_at: "Əlavə olunub",
    }
    column_default_sort = [(MedicinePrice.baslama_tarixi, True)]
    form_columns = [
        MedicinePrice.medicine,
        MedicinePrice.qiymet,
        MedicinePrice.baslama_tarixi,
    ]

    async def on_model_change(self, data, model, is_created, request) -> None:
        if (data.get("qiymet") or 0) <= 0:
            raise ValueError("Qiymət 0-dan böyük olmalıdır")
        kim_yaratdi(model, is_created, request)


class StockAdmin(ModelView, model=StockMovement):
    name = "Stok hərəkəti"
    name_plural = "Stok daxilolmaları"
    icon = "fa-solid fa-boxes-stacked"

    # Admin yalnız daxilolma əlavə edir; satış və geri qaytarma nümayəndədən gəlir
    can_edit = False
    can_delete = False

    column_list = [
        StockMovement.id,
        StockMovement.point,
        StockMovement.medicine,
        StockMovement.novu,
        StockMovement.say,
        StockMovement.tarix,
    ]
    column_labels = {
        StockMovement.point: "Aptek/depo",
        StockMovement.medicine: "Dərman",
        StockMovement.novu: "Növ",
        StockMovement.say: "Say",
        StockMovement.tarix: "Tarix",
        StockMovement.sebeb: "Səbəb",
    }
    column_default_sort = [(StockMovement.tarix, True)]
    form_columns = [
        StockMovement.point,
        StockMovement.medicine,
        StockMovement.say,
        StockMovement.tarix,
        StockMovement.sebeb,
    ]

    async def on_model_change(self, data, model, is_created, request) -> None:
        if (data.get("say") or 0) <= 0:
            raise ValueError("Say 0-dan böyük olmalıdır")
        if is_created:
            model.novu = "daxilolma"
            model.user_id = request.session.get("admin_id")
        kim_yaratdi(model, is_created, request)


class SettingAdmin(IzMixin, ModelView, model=Setting):
    name = "Ayar"
    name_plural = "Ayarlar"
    icon = "fa-solid fa-gear"

    can_delete = False

    column_list = [Setting.acar, Setting.deyer]
    column_labels = {Setting.acar: "Ayar", Setting.deyer: "Dəyər"}
    form_columns = [Setting.acar, Setting.deyer]


def admin_qur(app) -> Admin:
    admin = Admin(
        app,
        engine,
        authentication_backend=AdminAuth(secret_key=GIZLI_ACAR + "-admin-sessiya"),
        title="MedStock Admin",
    )
    for gorunus in (
        UserAdmin,
        RegionAdmin,
        UserRegionAdmin,
        ClinicAdmin,
        DoctorAdmin,
        PointAdmin,
        MedicineAdmin,
        SettingAdmin,
        MedicinePriceAdmin,
        StockAdmin,
    ):
        admin.add_view(gorunus)
    return admin