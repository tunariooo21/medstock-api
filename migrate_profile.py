"""Bir dəfəlik miqrasiya: profil və şifrə bərpası sahələri.

İşə salma:  python migrate_profile.py
Postgres üçündür (Render). Təkrar işə salmaq təhlükəsizdir.
"""

from sqlalchemy import text

from database import engine

KOMUTLAR = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS telefon VARCHAR",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp VARCHAR",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)",
    """
    CREATE TABLE IF NOT EXISTS password_resets (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        kod_hash VARCHAR NOT NULL,
        bitme TIMESTAMP WITH TIME ZONE NOT NULL,
        istifade BOOLEAN NOT NULL DEFAULT FALSE,
        cehd INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_password_resets_user_id ON password_resets (user_id)",
]


def main() -> None:
    with engine.begin() as baglanti:
        for komut in KOMUTLAR:
            baglanti.execute(text(komut))
            print("OK:", komut.splitlines()[0].strip())
    print("Miqrasiya tamamlandı.")


if __name__ == "__main__":
    main()
