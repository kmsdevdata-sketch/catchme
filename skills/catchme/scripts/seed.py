#!/usr/bin/env python3
"""F4 — deterministic bulk seeding from the migrated schema.

  seed.py schema-sql                       SQL that dumps the public schema as JSON (run by the wrapper)
  seed.py plan --schema F [--config F]     prints the seed SQL (FK order, generate_series, hash-based values)
  seed.py exports-sql [--config F]         SQL that dumps ownership maps for k6 `{own:name}` (or nothing)

Values are derived from hashtext(seed:table:column:i), so the same seed + schema gives the same data.
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import die, info, pp_dir, quote_ident as qi, read_json, read_yaml, sql_literal  # noqa: E402

DEFAULT_PARENT_ROWS = 100
CHUNK = 200_000

SCHEMA_SQL = r"""
SELECT json_build_object(
  'columns', (SELECT COALESCE(json_agg(json_build_object(
      'table', c.table_name, 'column', c.column_name, 'type', c.data_type, 'udt', c.udt_name,
      'nullable', c.is_nullable = 'YES', 'default', c.column_default,
      'identity', c.is_identity = 'YES', 'generated', c.is_generated <> 'NEVER',
      'maxlen', c.character_maximum_length, 'pos', c.ordinal_position)
      ORDER BY c.table_name, c.ordinal_position), '[]'::json)
    FROM information_schema.columns c
    JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name
    WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'),
  'pks', (SELECT COALESCE(json_agg(json_build_object('table', cl.relname, 'column', a.attname)), '[]'::json)
    FROM pg_constraint con
    JOIN pg_class cl ON cl.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = cl.relnamespace
    JOIN LATERAL unnest(con.conkey) AS k(attnum) ON true
    JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
    WHERE con.contype = 'p' AND n.nspname = 'public'),
  'fks', (SELECT COALESCE(json_agg(json_build_object('table', cl.relname, 'column', a.attname,
                                                     'ref_table', rcl.relname, 'ref_column', ra.attname)), '[]'::json)
    FROM pg_constraint con
    JOIN pg_class cl ON cl.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = cl.relnamespace
    JOIN pg_class rcl ON rcl.oid = con.confrelid
    JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord) ON true
    JOIN LATERAL unnest(con.confkey) WITH ORDINALITY AS rk(attnum, ord) ON rk.ord = k.ord
    JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
    JOIN pg_attribute ra ON ra.attrelid = con.confrelid AND ra.attnum = rk.attnum
    WHERE con.contype = 'f' AND n.nspname = 'public'),
  'enums', (SELECT COALESCE(json_object_agg(t.typname, labels), '{}'::json) FROM (
      SELECT t.typname, json_agg(e.enumlabel ORDER BY e.enumsortorder) AS labels
      FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid GROUP BY t.typname) t)
);
"""

INT_TYPES = {"integer", "bigint", "smallint"}
NOW_DEFAULT = re.compile(r"(now\(\)|current_timestamp|clock_timestamp\(\)|statement_timestamp\(\)|localtimestamp)", re.I)


class Schema:
    def __init__(self, data):
        self.cols = {}
        for c in data.get("columns") or []:
            self.cols.setdefault(c["table"], []).append(c)
        self.pk = {}
        for p in data.get("pks") or []:
            self.pk.setdefault(p["table"], []).append(p["column"])
        self.fks = {}
        for f in data.get("fks") or []:
            self.fks.setdefault(f["table"], {})[f["column"]] = (f["ref_table"], f["ref_column"])
        self.enums = data.get("enums") or {}

    def col(self, table, name):
        for c in self.cols.get(table, []):
            if c["column"] == name:
                return c
        return None


def hexpr(seed, table, column, idx="g.i"):
    """Deterministic non-negative int from (seed, table, column, row index)."""
    return f"(hashtext({sql_literal(f'{seed}:{table}:{column}:')} || {idx})::bigint & 2147483647)"


def key_expr(schema, seed, table, idx):
    """Expression for the PK value of row `idx` of `table` (must match what we insert)."""
    pks = schema.pk.get(table) or []
    if len(pks) != 1:
        return None
    c = schema.col(table, pks[0])
    t = c["type"]
    if t in INT_TYPES:
        return f"({idx})"
    if t == "uuid":
        return f"(md5({sql_literal(f'{seed}:{table}:pk:')} || {idx})::uuid)"
    if t in ("text", "character varying", "character"):
        return f"({sql_literal(table.lower() + '-')} || {idx})"
    return None


def value_expr(schema, seed, table, c, rows_of):
    name, t, udt = c["column"], c["type"], c["udt"]
    h = hexpr(seed, table, name)
    fk = schema.fks.get(table, {}).get(name)
    if fk:
        ref_table, _ = fk
        n = rows_of.get(ref_table)
        if not n:
            if c["nullable"]:
                return "NULL"
            die(f"{table}.{name} references {ref_table} which is not seeded — add it to seed.yaml tables")
        if ref_table == table:
            idx = f"(CASE WHEN g.i = 1 THEN 1 ELSE 1 + ({h} % (g.i - 1)) END)"
            ke = key_expr(schema, seed, table, idx)
            if ke is None:
                return "NULL" if c["nullable"] else die(f"self-reference {table}.{name}: add an override")
            return f"(CASE WHEN g.i = 1 THEN NULL ELSE {ke} END)" if c["nullable"] else ke
        idx = f"(1 + ({h} % {n}))"
        ke = key_expr(schema, seed, ref_table, idx)
        if ke is None:
            die(f"{table}.{name} → {ref_table}: composite or unsupported PK type — add an override in seed.yaml")
        return ke
    if t in INT_TYPES:
        return f"({h} % {100 if t == 'smallint' else 1000})" + ("::smallint" if t == "smallint" else "")
    if t in ("numeric", "real", "double precision", "money"):
        return f"round((({h} % 100000) / 100.0)::numeric, 2)" + ("::money" if t == "money" else "")
    if t in ("text", "character varying", "character", "citext"):
        base = f"({sql_literal(name + '_')} || g.i || '_' || substr(md5({sql_literal(f'{seed}:{table}:{name}:')} || g.i), 1, 8))"
        return f"left({base}, {c['maxlen']})" if c.get("maxlen") else base
    if t == "boolean":
        return f"(({h} % 2) = 0)"
    if t.startswith("timestamp"):
        return f"(timestamp '2025-01-01' + (({h} % 31536000) * interval '1 second'))"
    if t == "date":
        return f"(date '2025-01-01' + ({h} % 365)::int)"
    if t.startswith("time"):
        return f"(time '00:00' + (({h} % 86400) * interval '1 second'))"
    if t == "uuid":
        return f"(md5({sql_literal(f'{seed}:{table}:{name}:')} || g.i)::uuid)"
    if t in ("json", "jsonb"):
        return f"'{{}}'::{t}"
    if t == "bytea":
        return f"decode(md5({sql_literal(name)} || g.i), 'hex')"
    if t == "ARRAY":
        return f"'{{}}'::{udt.lstrip('_')}[]"
    if t == "USER-DEFINED" and udt in schema.enums:
        labels = schema.enums[udt]
        arr = "ARRAY[" + ", ".join(sql_literal(x) for x in labels) + f"]::{qi(udt)}[]"
        return f"({arr})[1 + ({h} % {len(labels)})]"
    if t == "inet":
        return f"('10.0.' || ({h} % 255) || '.' || (g.i % 255))::inet"
    if c["nullable"]:
        return "NULL"
    die(f"{table}.{name}: no generator for type {t}/{udt} — add an override in seed.yaml")


def topo(tables, schema):
    order, seen, stack = [], set(), set()

    def visit(t):
        if t in seen:
            return
        if t in stack:
            return  # cycle: the nullable side will be NULL
        stack.add(t)
        for _, (ref, _) in schema.fks.get(t, {}).items():
            if ref != t and ref in tables:
                visit(ref)
        stack.discard(t)
        seen.add(t)
        order.append(t)

    for t in sorted(tables):
        visit(t)
    return order


def normalize_tables(cfg):
    out = {}
    for name, v in (cfg.get("tables") or {}).items():
        rows = v.get("rows") if isinstance(v, dict) else v
        if not isinstance(rows, int) or rows < 0:
            die(f"seed.yaml tables.{name}: rows must be a non-negative integer")
        out[name] = rows
    return out


def plan(schema, cfg):
    seed = cfg.get("seed", 42)
    wanted = normalize_tables(cfg)
    missing = [t for t in wanted if t not in schema.cols]
    if missing:
        known = ", ".join(sorted(schema.cols)) or "(none — did the app run its migrations?)"
        die(f"tables not in DB: {', '.join(missing)}. Known tables: {known}")

    rows_of = dict(wanted)
    frontier = list(wanted)
    while frontier:  # add FK ancestors that were not listed
        t = frontier.pop()
        for col, (ref, _) in schema.fks.get(t, {}).items():
            c = schema.col(t, col)
            if ref not in rows_of and not (c and c["nullable"]):
                rows_of[ref] = DEFAULT_PARENT_ROWS
                info(f"{ref} not in seed.yaml but referenced by {t}.{col} → {DEFAULT_PARENT_ROWS} rows")
                frontier.append(ref)

    overrides = cfg.get("overrides") or {}
    order = topo(set(rows_of), schema)
    out = ["-- generated by catchme seed.py — deterministic (seed=%s)" % seed,
           "\\set ON_ERROR_STOP on",
           "SET synchronous_commit = off;",
           "SET client_min_messages = warning;",
           "TRUNCATE " + ", ".join(qi(t) for t in order) + " RESTART IDENTITY CASCADE;"]

    for t in order:
        n = rows_of[t]
        if n == 0:
            continue
        cols, exprs, has_identity = [], [], False
        pks = schema.pk.get(t) or []
        tov = overrides.get(t) or {}
        unknown = [k for k in tov if not schema.col(t, k)]
        if unknown:
            die(f"seed.yaml overrides.{t}: unknown columns {', '.join(unknown)}")
        for c in schema.cols[t]:
            name = c["column"]
            if c["generated"]:
                continue
            if name in tov:
                cols.append(qi(name))
                exprs.append(f"({str(tov[name]).strip()})".replace("{seed}", str(seed)))
                if c["identity"]:
                    has_identity = True
                continue
            if name in pks and len(pks) == 1:
                ke = key_expr(schema, seed, t, "g.i")
                if ke is not None:
                    cols.append(qi(name))
                    exprs.append(ke)
                    has_identity = has_identity or c["identity"]
                    continue
            if c["default"] and not NOW_DEFAULT.search(str(c["default"])) and name not in schema.fks.get(t, {}):
                continue  # let DB defaults apply (serial handled above, nextval elsewhere, constants)
            if c["identity"]:
                continue
            cols.append(qi(name))
            exprs.append(value_expr(schema, seed, t, c, rows_of))
        overriding = " OVERRIDING SYSTEM VALUE" if has_identity else ""
        out.append(f"\\echo seeding {t}: {n:,} rows")
        for start in range(1, n + 1, CHUNK):
            end = min(n, start + CHUNK - 1)
            select = ", ".join(exprs)
            out.append(f"INSERT INTO {qi(t)} ({', '.join(cols)}){overriding}\n"
                       f"SELECT {select}\nFROM generate_series({start}, {end}) AS g(i)\n"
                       f"ON CONFLICT DO NOTHING;")
        if len(pks) == 1 and schema.col(t, pks[0])["type"] in INT_TYPES:
            pk = pks[0]
            seq = f"pg_get_serial_sequence({sql_literal(qi(t))}, {sql_literal(pk)})"
            out.append(f"DO $$ BEGIN IF {seq} IS NOT NULL THEN PERFORM setval({seq}, "
                       f"GREATEST((SELECT COALESCE(MAX({qi(pk)}), 0) FROM {qi(t)}), 1)); END IF; END $$;")
    out.append("ANALYZE;")
    body = "\n".join(out) + "\n"
    digest = hashlib.sha256(body.encode()).hexdigest()[:16]
    body += ("INSERT INTO catchme.meta(key, value) VALUES ('seed_sha', %s) "
             "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;\n") % sql_literal(digest)
    return body, digest


def exports_sql(cfg):
    ex = cfg.get("exports") or {}
    if not ex:
        return ""
    parts = []
    for name, sql in ex.items():
        if not re.match(r"^\w+$", str(name)):
            die(f"export name '{name}' must be alphanumeric/underscore")
        q = str(sql).strip().rstrip(";")
        parts.append(
            f"SELECT {sql_literal(name)} AS name, COALESCE(json_object_agg(owner, ids), '{{}}'::json) AS m FROM ("
            f"SELECT owner::text AS owner, (array_agg(id ORDER BY id))[1:200] AS ids FROM ({q}) x GROUP BY owner) y")
    return ("SELECT COALESCE(json_object_agg(name, m), '{}'::json) FROM (\n" +
            "\nUNION ALL\n".join(parts) + "\n) z;\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("schema-sql")
    p = sub.add_parser("plan")
    p.add_argument("--schema", required=True)
    p.add_argument("--config", default=None)
    p.add_argument("--digest-out")
    e = sub.add_parser("exports-sql")
    e.add_argument("--config", default=None)
    a = ap.parse_args()

    if a.cmd == "schema-sql":
        sys.stdout.write(SCHEMA_SQL)
        return
    cfg_path = Path(a.config) if a.config else pp_dir() / "seed.yaml"
    cfg = read_yaml(cfg_path)
    if a.cmd == "plan":
        schema = Schema(read_json(a.schema))
        body, digest = plan(schema, cfg)
        sys.stdout.write(body)
        if a.digest_out:
            Path(a.digest_out).write_text(digest + "\n")
    elif a.cmd == "exports-sql":
        sys.stdout.write(exports_sql(cfg))


if __name__ == "__main__":
    main()
