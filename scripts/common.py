"""Shared plumbing: SQLite store (schema.sql), deterministic ids, polite HTTP, run logging, source registry."""
from __future__ import annotations
import hashlib, json, sqlite3, time, traceback, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
import os
DB = Path(os.environ.get("SM_DB", ROOT / "data" / "smartmoney.db"))
IST = timezone(timedelta(hours=5, minutes=30))
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def now():
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M")


def today():
    return datetime.now(IST).date()


def hid(*parts):
    return hashlib.sha1("|".join("" if p is None else str(p) for p in parts).encode()).hexdigest()[:16]


def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=OFF")
    con.executescript((ROOT / "schema.sql").read_text())
    migrate(con)
    return con


def migrate(con):
    """Add columns introduced after a database was first created (CREATE TABLE IF NOT EXISTS does not alter)."""
    have = {r[1] for r in con.execute("PRAGMA table_info(ownership)")}
    for col, typ in (("quantity", "REAL"), ("value_inr_cr", "REAL"), ("pct_of_nav", "REAL"), ("scheme_flag", "TEXT")):
        if col not in have:
            con.execute(f"ALTER TABLE ownership ADD COLUMN {col} {typ}")
    con.execute("CREATE INDEX IF NOT EXISTS ix_own_cat_period ON ownership(holder_category, period_end)")
    con.commit()


def upsert(con, table, row, key):
    cols = list(row)
    q = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) ON CONFLICT({key}) DO UPDATE SET " + \
        ",".join(f"{c}=excluded.{c}" for c in cols if c != key)
    con.execute(q, [row[c] for c in cols])


def insert_new(con, table, row, key):
    """Insert if the deterministic id is new. Returns True if inserted (False = duplicate skipped)."""
    cols = list(row)
    cur = con.execute(f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [row[c] for c in cols])
    return cur.rowcount == 1


def doc(con, source_id, url, title=None, publication_date=None, data_period=None, label="VERIFIED FACT", content=None):
    d = hid(source_id, url, data_period)
    upsert(con, "source_documents", dict(doc_id=d, source_id=source_id, url=url, title=title, publication_date=publication_date,
                                         data_period=data_period, retrieved_at=now(),
                                         content_hash=hashlib.sha1(content).hexdigest()[:16] if content else None,
                                         evidence_label=label), "doc_id")
    return d


def obs(con, source_id, metric, entity_type, entity_id, period_end, value, unit, period_start=None, doc_id=None, label="VERIFIED FACT"):
    o = hid(source_id, metric, entity_type, entity_id, period_start, period_end)
    upsert(con, "observations", dict(obs_id=o, source_id=source_id, metric=metric, entity_type=entity_type, entity_id=entity_id,
                                     period_start=period_start, period_end=period_end, value=value, unit=unit,
                                     evidence_label=label, doc_id=doc_id), "obs_id")
    return o


class Http:
    def __init__(self, nse=False):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"})
        self.nse_ready = False
        if nse:
            self.warm_nse()

    def warm_nse(self):
        try:
            self.s.get("https://www.nseindia.com/", timeout=25)
            self.nse_ready = True
        except Exception:
            pass

    def get(self, url, tries=3, timeout=45, pause=1.0, **kw):
        err = None
        for i in range(tries):
            try:
                h = kw.pop("headers", None) or {}
                if "nseindia.com/api" in url:
                    h = {"Referer": "https://www.nseindia.com/", "Accept": "application/json", **h}
                r = self.s.get(url, timeout=timeout, headers=h, **kw)
                if r.status_code == 200:
                    time.sleep(pause)
                    return r
                err = f"HTTP {r.status_code}"
                if r.status_code in (401, 403) and "nseindia" in url:
                    self.warm_nse()
            except Exception as e:  # noqa: BLE001
                err = str(e)[:200]
            time.sleep(3 * (i + 1))
        raise RuntimeError(f"{url}: {err}")


def log_run(con, source_id, ok, rows_in=0, rows_new=0, dup=0, error=None, period=None, pub=None):
    t = now()
    upsert(con, "extraction_logs", dict(log_id=hid(source_id, t, ok), source_id=source_id, run_at=t, ok=int(ok), rows_in=rows_in,
                                        rows_new=rows_new, duplicates_skipped=dup, error=(error or "")[:500] or None), "log_id")
    con.execute("UPDATE sources SET last_attempt=? WHERE source_id=?", (t, source_id))
    if ok:
        con.execute("UPDATE sources SET last_success=?, status=CASE WHEN status IN ('blocked','not_built') THEN 'working' ELSE status END WHERE source_id=?", (t, source_id))
        if period:
            con.execute("UPDATE sources SET latest_data_period=? WHERE source_id=?", (period, source_id))
        if pub:
            con.execute("UPDATE sources SET latest_publication_date=? WHERE source_id=?", (pub, source_id))
    con.commit()


def run(source_id, fn, *a, **kw):
    """Run one ingestion job; failures are logged, never fatal, and never wipe earlier good data."""
    con = connect()
    try:
        res = fn(con, *a, **kw) or {}
        log_run(con, source_id, True, res.get("rows_in", 0), res.get("rows_new", 0), res.get("dup", 0), res.get("warn"),
                res.get("period"), res.get("pub"))
        print(f"[ok] {source_id}: {res}")
        return True
    except Exception as e:  # noqa: BLE001
        con.rollback()
        log_run(con, source_id, False, error=f"{type(e).__name__}: {e}")
        print(f"[FAIL] {source_id}: {e}")
        traceback.print_exc()
        return False
    finally:
        con.close()


def num(x):
    if x is None:
        return None
    try:
        s = str(x).replace(",", "").strip()
        if s in ("", "-", "NA", "N.A.", "nan"):
            return None
        return float(s)
    except ValueError:
        return None


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
