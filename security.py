import bcrypt


def parol_hashle(parol: str) -> str:
    return bcrypt.hashpw(parol.encode(), bcrypt.gensalt()).decode()


def parol_yoxla(parol: str, parol_hash: str) -> bool:
    return bcrypt.checkpw(parol.encode(), parol_hash.encode())