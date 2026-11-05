from sqlalchemy import text

from database import engine

try:
    with engine.connect() as conn:
        print(conn.execute(text("select version()")).scalar())
except Exception as e:
    print("Xətanın növü:", type(e).__name__)
    print(str(e)[:700])