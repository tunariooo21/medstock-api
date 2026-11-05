from sqlmodel import Session

from database import engine
from models import Setting

with Session(engine) as session:
    if not session.get(Setting, "asagi_qaliq_hedd"):
        session.add(Setting(acar="asagi_qaliq_hedd", deyer="20"))
        session.commit()
    print("Hazırdır.")