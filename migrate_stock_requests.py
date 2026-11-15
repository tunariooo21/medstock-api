from sqlalchemy import text
from sqlmodel import SQLModel

from database import engine
from models import Notification, StockRequest, StockRequestRow, UserPhoto


def main():
    if engine.dialect.name != "postgresql":
        raise RuntimeError("This migration requires PostgreSQL")
    tables = [m.__table__ for m in (StockRequest, StockRequestRow, Notification, UserPhoto)]
    with engine.begin() as conn:
        SQLModel.metadata.create_all(conn, tables=tables)
        for table in tables:
            conn.execute(text(f'ALTER TABLE public."{table.name}" ENABLE ROW LEVEL SECURITY'))
    print("Stock request, notification and profile photo tables are ready")


if __name__ == "__main__":
    main()
