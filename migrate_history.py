from sqlmodel import SQLModel

from database import engine
import models  # noqa: F401  (modelləri qeydiyyata alır)

# Yalnız yeni cədvəlləri yaradır, mövcudlara toxunmur.
SQLModel.metadata.create_all(engine)
print("record_audits cədvəli hazırdır")
