"""Versioned, additive schema migrations for Smart Money Intelligence 2.0.
Each file migrations/NNN_name.sql runs once, inside one transaction, and is recorded in schema_migrations with a checksum.
An already-applied file whose content changed is refused (write a new migration instead). v1 tables are never altered here.
Usage: python3 scripts/migrate.py [--status]"""
from __future__ import annotations
import hashlib, re, sqlite3, sys
from pathlib import Path
from common import ROOT, connect, now

MIG_DIR = ROOT / "migrations"
REGISTRY = """CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"""


class MigrationError(RuntimeError):
    pass


def files(mig_dir: Path = MIG_DIR):
    out = []
    for p in sorted(mig_dir.glob("*.sql")):
        m = re.match(r"^(\d{3})_(.+)\.sql$", p.name)
        if m:
            out.append((m.group(1), m.group(2), p))
    return out


def checksum(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def applied(con) -> dict:
    con.execute(REGISTRY)
    return {r[0]: (r[1], r[2]) for r in con.execute("SELECT version, name, checksum FROM schema_migrations")}


def apply_all(con: sqlite3.Connection, mig_dir: Path = MIG_DIR) -> list:
    done = applied(con)
    ran = []
    for ver, name, p in files(mig_dir):
        cs = checksum(p)
        if ver in done:
            if done[ver][1] != cs:
                raise MigrationError(f"migration {p.name} was already applied with a different checksum; never edit an applied migration, add a new one")
            continue
        sql = p.read_text()
        con.commit()
        try:
            con.execute("BEGIN")
            for stmt in split_sql(sql):
                con.execute(stmt)
            con.execute("INSERT INTO schema_migrations(version, name, checksum, applied_at) VALUES (?,?,?,?)", (ver, name, cs, now()))
            con.execute("COMMIT")
        except Exception as e:
            con.execute("ROLLBACK")
            raise MigrationError(f"{p.name} failed and was rolled back: {e}") from e
        ran.append(p.name)
    return ran


def split_sql(sql: str):
    """Split on semicolons outside BEGIN...END trigger bodies; strips -- comments."""
    lines = [ln.split("--", 1)[0] if not ln.strip().startswith("--") else "" for ln in sql.splitlines()]
    text = "\n".join(lines)
    out, buf, depth = [], [], 0
    for tok in re.split(r"(;)", text):
        if tok == ";":
            buf.append(tok)
            joined = "".join(buf)
            if depth == 0 or re.search(r"\bEND\s*;\s*$", joined, re.I):
                if joined.strip(" ;\n"):
                    out.append(joined.strip())
                buf, depth = [], 0
            continue
        if re.search(r"\bCREATE\s+TRIGGER\b", tok, re.I):
            depth = 1
        buf.append(tok)
    if "".join(buf).strip():
        out.append("".join(buf).strip())
    return out


def main():
    con = connect()
    if "--status" in sys.argv:
        print(applied(con))
        return
    ran = apply_all(con)
    print("applied:", ran or "nothing new", "| registry:", sorted(applied(con)))


if __name__ == "__main__":
    main()
