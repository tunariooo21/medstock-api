from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, Index, Numeric, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel


def indi() -> datetime:
    return datetime.now(timezone.utc)


def yaradilma_vaxti():
    return Field(default_factory=indi, sa_type=DateTime(timezone=True))


def yaradan():
    return Field(default=None, foreign_key="users.id")


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    login: str = Field(unique=True, index=True)
    ad: str
    rol: str  # "admin", "manager" və ya "representative"
    parol_hash: str
    manager_id: int | None = Field(default=None, foreign_key="users.id", index=True)
    active: bool = True
    created_at: datetime = yaradilma_vaxti()
    created_by: int | None = yaradan()

    manager: Optional["User"] = Relationship(
        sa_relationship_kwargs={
            "remote_side": "User.id",
            "foreign_keys": "User.manager_id",
        }
    )

    def __str__(self) -> str:
        return f"{self.ad} ({self.login})"


class Region(SQLModel, table=True):
    __tablename__ = "regions"

    id: int | None = Field(default=None, primary_key=True)
    ad: str = Field(unique=True)
    active: bool = True
    created_at: datetime = yaradilma_vaxti()
    created_by: int | None = yaradan()

    def __str__(self) -> str:
        return self.ad


class UserRegion(SQLModel, table=True):
    __tablename__ = "user_regions"

    user_id: int = Field(foreign_key="users.id", primary_key=True)
    region_id: int = Field(foreign_key="regions.id", primary_key=True)
    created_at: datetime = yaradilma_vaxti()
    created_by: int | None = yaradan()

    user: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "UserRegion.user_id"}
    )
    region: Optional["Region"] = Relationship()

    def __str__(self) -> str:
        return f"{self.user} → {self.region}"


class Point(SQLModel, table=True):
    """Aptek və depolar."""

    __tablename__ = "points"

    id: int | None = Field(default=None, primary_key=True)
    ad: str
    novu: str  # "aptek" və ya "depo"
    region_id: int = Field(foreign_key="regions.id", index=True)
    unvan: str | None = None
    active: bool = True
    created_at: datetime = yaradilma_vaxti()
    created_by: int | None = yaradan()

    region: Optional["Region"] = Relationship()

    def __str__(self) -> str:
        return f"{self.ad} ({self.novu})"


class Clinic(SQLModel, table=True):
    __tablename__ = "clinics"

    id: int | None = Field(default=None, primary_key=True)
    ad: str
    region_id: int = Field(foreign_key="regions.id", index=True)
    unvan: str | None = None
    active: bool = True
    created_at: datetime = yaradilma_vaxti()
    created_by: int | None = yaradan()

    region: Optional["Region"] = Relationship()

    def __str__(self) -> str:
        return self.ad


class Doctor(SQLModel, table=True):
    __tablename__ = "doctors"

    id: int | None = Field(default=None, primary_key=True)
    ad: str
    ixtisas: str | None = None
    telefon: str | None = None
    clinic_id: int = Field(foreign_key="clinics.id", index=True)
    active: bool = True
    created_at: datetime = yaradilma_vaxti()
    created_by: int | None = yaradan()

    clinic: Optional["Clinic"] = Relationship()

    def __str__(self) -> str:
        return self.ad


class Medicine(SQLModel, table=True):
    __tablename__ = "medicines"

    id: int | None = Field(default=None, primary_key=True)
    ad: str = Field(unique=True)
    forma: str | None = None
    active: bool = True
    created_at: datetime = yaradilma_vaxti()
    created_by: int | None = yaradan()

    def __str__(self) -> str:
        return self.ad


class MedicinePrice(SQLModel, table=True):
    """Qiymət dəyişəndə köhnə sətir silinmir, yeni sətir əlavə olunur."""

    __tablename__ = "medicine_prices"

    id: int | None = Field(default=None, primary_key=True)
    medicine_id: int = Field(foreign_key="medicines.id", index=True)
    qiymet: Decimal = Field(sa_type=Numeric(10, 2))
    baslama_tarixi: date  # qüvvəyə minmə tarixi
    created_at: datetime = yaradilma_vaxti()
    created_by: int | None = yaradan()

    medicine: Optional["Medicine"] = Relationship()


class StockMovement(SQLModel, table=True):
    """Daxilolma, satış və geri qaytarma. Qalıq bu qeydlərdən hesablanır."""

    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint("say > 0", name="ck_stock_movements_say"),
        Index("ix_stock_movements_nokte_derman_tarix", "point_id", "medicine_id", "tarix"),
    )

    id: int | None = Field(default=None, primary_key=True)
    point_id: int = Field(foreign_key="points.id")
    medicine_id: int = Field(foreign_key="medicines.id")
    user_id: int = Field(foreign_key="users.id")
    novu: str  # "daxilolma", "satis" və ya "geri_qaytarma"
    say: int
    tarix: date
    sebeb: str | None = None
    created_at: datetime = yaradilma_vaxti()
    created_by: int | None = yaradan()

    point: Optional["Point"] = Relationship()
    medicine: Optional["Medicine"] = Relationship()


class Prescription(SQLModel, table=True):
    __tablename__ = "prescriptions"
    __table_args__ = (
        CheckConstraint("say > 0", name="ck_prescriptions_say"),
        Index("ix_prescriptions_nokte_derman_tarix", "point_id", "medicine_id", "tarix"),
    )

    id: int | None = Field(default=None, primary_key=True)
    point_id: int = Field(foreign_key="points.id")
    medicine_id: int = Field(foreign_key="medicines.id")
    doctor_id: int = Field(foreign_key="doctors.id")
    say: int  # resept sayı
    tarix: date
    created_at: datetime = yaradilma_vaxti()
    created_by: int | None = yaradan()


class MonthlyReport(SQLModel, table=True):
    __tablename__ = "monthly_reports"
    __table_args__ = (UniqueConstraint("user_id", "ay", name="uq_monthly_reports_user_ay"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)  # hesabatın sahibi (işçi)
    ay: date  # ayın birinci günü
    status: str = "qaralama"  # qaralama, gonderildi, geri_qaytarildi, tesdiqlendi
    menecer_serhi: str | None = None
    created_at: datetime = yaradilma_vaxti()
    created_by: int | None = yaradan()


class MonthlyReportRow(SQLModel, table=True):
    __tablename__ = "monthly_report_rows"
    __table_args__ = (
        UniqueConstraint("report_id", "doctor_id", "medicine_id", name="uq_report_rows"),
        CheckConstraint("say >= 0", name="ck_report_rows_say"),
    )

    id: int | None = Field(default=None, primary_key=True)
    report_id: int = Field(foreign_key="monthly_reports.id", index=True)
    doctor_id: int = Field(foreign_key="doctors.id")
    medicine_id: int = Field(foreign_key="medicines.id")
    say: int = 0
    created_at: datetime = yaradilma_vaxti()
    created_by: int | None = yaradan()


class Setting(SQLModel, table=True):
    """Sistem ayarları (açar-dəyər). Məsələn: asagi_qaliq_hedd."""

    __tablename__ = "settings"

    acar: str = Field(primary_key=True)
    deyer: str
    created_at: datetime = yaradilma_vaxti()
    created_by: int | None = yaradan()