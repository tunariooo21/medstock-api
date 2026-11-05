import os

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

load_dotenv()
raw = os.environ.get("DATABASE_URL", "")

print("Uzunluq:", len(raw))
print("Prefiks:", raw.split("://")[0] if "://" in raw else "YOXDUR")
print("'@' sayı (1 olmalıdır):", raw.count("@"))
print("Mötərizə var:", "[" in raw or "]" in raw)
print("Dırnaq və ya boşluq var:", '"' in raw or "'" in raw or " " in raw)

try:
    u = make_url(raw)
    print("host:", u.host)
    print("port:", u.port)
    print("istifadəçi (ilk hissə):", (u.username or "").split(".")[0])
    print("baza:", u.database)
except Exception as e:
    print("Sətir oxunmadı:", e)