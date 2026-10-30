import json

from scraper.models.typed_tables import TABLES, TypedTable
from scraper.repositories.typed_repository import TypedRepository


def _upsert_sql(table: TypedTable) -> str:
    cols = table.column_names
    names = ", ".join(f'"{c}"' for c in cols)
    params = ", ".join(f"%({c})s" + ("::jsonb" if t == "JSONB" else "") for c, t in table.columns)
    updates = [f'"{c}" = EXCLUDED."{c}"' for c in cols if c not in table.key] + ["updated_at = now()"]
    key = ", ".join(f'"{k}"' for k in table.key)
    return (
        f'INSERT INTO "{table.name}" ({names}) VALUES ({params}) '
        f"ON CONFLICT ({key}) DO UPDATE SET {', '.join(updates)}"
    )


UPSERT_SQL = {name: _upsert_sql(t) for name, t in TABLES.items()}


class PostgresTypedRepositoryAdapter(TypedRepository):
    def __init__(self, conn):
        self.conn = conn

    def upsert_rows(self, table: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        spec = TABLES[table]
        json_cols = [c for c, t in spec.columns if t == "JSONB"]
        # De-duplicate within the batch: ON CONFLICT can't hit the same key twice per statement.
        unique = {tuple(r[k] for k in spec.key): r for r in rows}
        params = [
            {**r, **{c: None if r[c] is None else json.dumps(r[c]) for c in json_cols}} for r in unique.values()
        ]
        with self.conn.transaction():
            with self.conn.cursor() as cur:
                cur.executemany(UPSERT_SQL[table], params)
        return len(params)
