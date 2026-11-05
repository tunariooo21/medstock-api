from sqlalchemy import text
from sqlmodel import SQLModel

from database import engine
import models  # noqa: F401  (modelləri qeydiyyata alır)

SQLModel.metadata.create_all(engine)

# Supabase-in avtomatik REST API-si var, biz onu istifadə etmirik.
# Sətir səviyyəli təhlükəsizliyi (RLS) açmaq həmin yolu bağlayır;
# FastAPI serveri postgres rolu ilə qoşulduğu üçün işinə mane olmur.
with engine.begin() as conn:
    for ad in SQLModel.metadata.tables:
        conn.execute(text(f'ALTER TABLE public."{ad}" ENABLE ROW LEVEL SECURITY'))

print("Cədvəllər yaradıldı:")
for ad in sorted(SQLModel.metadata.tables):
    print(" -", ad)