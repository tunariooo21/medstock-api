import os

from dotenv import load_dotenv
from sqlmodel import create_engine

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

# SQLAlchemy-nin psycopg 3 sürücüsünü seçməsi üçün
for prefiks in ("postgres://", "postgresql://"):
    if DATABASE_URL.startswith(prefiks):
        DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len(prefiks):]
        break

engine = create_engine(DATABASE_URL, pool_pre_ping=True)