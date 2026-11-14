"""E-poçt göndərişi.

SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / SMTP_FROM mühit
dəyişənləri qurulmayıbsa demo rejimi işləyir: kod API cavabında qaytarılır.
"""

import os
import smtplib
from email.message import EmailMessage

SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or 587)
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", "").strip() or SMTP_USER


def konfiqurasiya_var() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASS)


class EmailXetasi(Exception):
    pass


def kod_gonder(alan: str, kod: str, ad: str = "") -> None:
    """Təsdiq kodunu e-poçtla göndərir. SMTP qurulmayıbsa EmailXetasi atılır."""
    if not konfiqurasiya_var():
        raise EmailXetasi("SMTP ayarları yoxdur")

    msg = EmailMessage()
    msg["Subject"] = "MedStock — şifrə yeniləmə kodu"
    msg["From"] = SMTP_FROM
    msg["To"] = alan
    msg.set_content(
        f"Salam{', ' + ad if ad else ''}!\n\n"
        f"Şifrənizi yeniləmək üçün təsdiq kodunuz: {kod}\n\n"
        "Kod 15 dəqiqə ərzində etibarlıdır. Bu sorğunu siz göndərməmisinizsə, "
        "məktubu nəzərə almayın.\n\n"
        "MedStock"
    )

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
    except Exception as xeta:  # noqa: BLE001
        raise EmailXetasi(str(xeta)) from xeta
