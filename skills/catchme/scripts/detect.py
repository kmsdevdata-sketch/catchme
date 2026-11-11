#!/usr/bin/env python3
"""F1 — project analysis → .prod-parity/project.json

Detects stack (spring-jpa | node-prisma | django), build tool, DB engine, port, endpoints,
auth style, Dockerfile, and non-local DB hosts in env files (host names only, never values).
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import die, info, looks_production, pp_dir, project_root, read_json, url_host, write_json  # noqa: E402

SKIP_DIRS = {".git", "node_modules", ".prod-parity", "build", "target", "dist", ".venv", "venv",
             "env", "__pycache__", ".gradle", ".idea", ".next", ".nuxt", "coverage", ".mvn",
             "out", "bin", "obj", "vendor", ".tox", ".pytest_cache", "static", "staticfiles"}
MAX_FILE_BYTES = 512 * 1024


def walk(root, exts=None, names=None, limit=30000):
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if names and fn in names or exts and fn.endswith(exts):
                p = Path(dirpath) / fn
                try:
                    if p.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                count += 1
                if count > limit:
                    return
                yield p


def read(p):
    try:
        return Path(p).read_text(errors="ignore")
    except OSError:
        return ""


def rel(root, p):
    return str(Path(p).relative_to(root))


def line_of(text, idx):
    return text.count("\n", 0, idx) + 1


def join_path(prefix, path):
    prefix = (prefix or "").strip()
    path = (path or "").strip()
    full = "/" + "/".join(x.strip("/") for x in (prefix, path) if x and x.strip("/"))
    return full if full != "" else "/"


# --------------------------------------------------------------------------- spring

def detect_spring(root):
    build_files = [p for p in (root / "build.gradle", root / "build.gradle.kts", root / "pom.xml") if p.exists()]
    if not build_files:
        return None
    text = "\n".join(read(p) for p in build_files)
    if "spring-boot" not in text and "org.springframework.boot" not in text:
        return None
    tool = "maven" if build_files[0].name == "pom.xml" else "gradle"
    db = "postgresql" if "postgresql" in text else ("mysql" if "mysql" in text else None)
    port = 8080
    for cfg in list(walk(root, names={"application.yml", "application.yaml", "application.properties"})):
        t = read(cfg)
        m = re.search(r"server\.port\s*[=:]\s*(\d+)", t) or re.search(r"server:\s*\n\s+port:\s*(\d+)", t)
        if m:
            port = int(m.group(1))
            break
    endpoints = []
    ann = re.compile(r"@(Get|Post|Put|Delete|Patch|Request)Mapping\s*(\(([^)]*)\))?")
    for src in walk(root, exts=(".java", ".kt")):
        t = read(src)
        if "Controller" not in t:
            continue
        cls = re.search(r"@RequestMapping\s*\(([^)]*)\)\s*(?:@\w+(?:\([^)]*\))?\s*)*(?:public\s+|open\s+)?(?:abstract\s+)?class", t)
        prefix = ""
        if cls:
            m = re.search(r'"([^"]*)"', cls.group(1))
            prefix = m.group(1) if m else ""
        class_pos = re.search(r"\bclass\s+\w+", t)
        for m in ann.finditer(t):
            if class_pos and m.start() < class_pos.start():
                continue
            kind, args = m.group(1), m.group(3) or ""
            pm = re.search(r'"([^"]*)"', args)
            method = kind.upper()
            if kind == "Request":
                mm = re.search(r"RequestMethod\.(\w+)", args)
                method = mm.group(1) if mm else "ANY"
            endpoints.append({"method": method, "path": join_path(prefix, pm.group(1) if pm else ""),
                              "file": rel(root, src), "line": line_of(t, m.start())})
    auth = []
    if "spring-boot-starter-security" in text:
        auth.append("spring-security")
    if re.search(r"jjwt|java-jwt|nimbus-jose|oauth2-resource-server", text):
        auth.append("jwt")
    if "oauth2-client" in text:
        auth.append("oauth")
    run = "./gradlew bootRun" if tool == "gradle" else "./mvnw spring-boot:run"
    return {
        "stack": "spring-jpa", "language": "java/kotlin", "build_tool": tool, "port": port,
        "db_engine": db, "db_source": rel(root, build_files[0]), "endpoints": endpoints,
        "auth_kinds": auth, "run_command": run,
        "query_file_globs": ["*Repository.java", "*Repository.kt", "*Mapper.xml", "*Dao.java"],
        "db_env": {
            "SPRING_DATASOURCE_URL": "jdbc:postgresql://{host}:{port}/{db}",
            "SPRING_DATASOURCE_USERNAME": "{user}",
            "SPRING_DATASOURCE_PASSWORD": "{password}",
            "SPRING_DATASOURCE_HIKARI_MAXIMUM_POOL_SIZE": "{pool}",
        },
        "default_pool": 10,
        "default_env": {},  # JVM flags must mirror production (Dockerfile / task definition), not a guess
        "score": 10,
    }


# --------------------------------------------------------------------------- node + prisma

DATASTORE_PORTS = {5432, 3306, 6379, 27017, 9200, 5672, 11211, 1433, 1521}
ROUTE_RE = re.compile(r"\b(app|router|server|fastify|api|routes|\w+Router|\w+Routes)\s*\.\s*(get|post|put|delete|patch)\s*\(\s*['\"`]([^'\"`]+)['\"`]")
NEST_CTRL = re.compile(r"@Controller\(\s*['\"`]?([^'\"`)]*)['\"`]?\s*\)")
NEST_ROUTE = re.compile(r"@(Get|Post|Put|Delete|Patch)\(\s*(?:['\"`]([^'\"`]*)['\"`])?\s*\)")


def node_pkg(root):
    pkg_path = root / "package.json"
    if not pkg_path.exists():
        return None, {}
    try:
        pkg = json.loads(read(pkg_path) or "{}")
    except json.JSONDecodeError:
        pkg = {}
    return pkg, {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}


def node_scan(root, pkg, deps):
    tool = "pnpm" if (root / "pnpm-lock.yaml").exists() else "yarn" if (root / "yarn.lock").exists() else "npm"
    endpoints, port = [], None
    for src in walk(root, exts=(".js", ".ts", ".mjs", ".cjs")):
        if ".d.ts" in src.name or src.name.endswith((".test.ts", ".spec.ts", ".test.js")):
            continue
        t = read(src)
        for m in ROUTE_RE.finditer(t):
            endpoints.append({"method": m.group(2).upper(), "path": m.group(3),
                              "file": rel(root, src), "line": line_of(t, m.start())})
        ctrl = NEST_CTRL.search(t)
        if ctrl:
            for m in NEST_ROUTE.finditer(t):
                endpoints.append({"method": m.group(1).upper(), "path": join_path(ctrl.group(1), m.group(2)),
                                  "file": rel(root, src), "line": line_of(t, m.start())})
        if port is None:
            # `PORT || 3000` but not `DB_PORT || 5432`; also skip well-known datastore ports
            for m in list(re.finditer(r"\.listen\(\s*(?:[\w.]*\bPORT\b\s*(?:\|\||\?\?)\s*)?(\d{2,5})", t)) + \
                     list(re.finditer(r"(?<![A-Za-z0-9_])PORT\s*(?:\|\||\?\?)\s*['\"]?(\d{2,5})", t)):
                if int(m.group(1)) not in DATASTORE_PORTS:
                    port = int(m.group(1))
                    break
    auth = []
    if any(k in deps for k in ("jsonwebtoken", "jose", "@nestjs/jwt", "passport-jwt", "express-jwt")):
        auth.append("jwt")
    if any(k in deps for k in ("express-session", "cookie-session", "iron-session")):
        auth.append("session")
    if any(k.startswith("passport-") and "jwt" not in k and "local" not in k for k in deps) or "next-auth" in deps:
        auth.append("oauth")
    start = pkg.get("scripts", {}).get("start")
    framework = "nestjs" if "@nestjs/core" in deps else "fastify" if "fastify" in deps else "express" if "express" in deps else "node"
    return {"language": "javascript/typescript", "build_tool": tool, "port": port or 3000, "endpoints": endpoints,
            "auth_kinds": auth, "run_command": f"{tool} start" if start else "node .", "framework": framework,
            "default_env": {"NODE_ENV": "production"}, "score": 10}


def detect_prisma(root):
    pkg, deps = node_pkg(root)
    if pkg is None or ("prisma" not in deps and "@prisma/client" not in deps):
        return None
    schema = None
    for cand in [root / "prisma" / "schema.prisma"] + list(walk(root, names={"schema.prisma"})):
        if cand.exists():
            schema = cand
            break
    db = None
    if schema:
        m = re.search(r'provider\s*=\s*"(postgresql|mysql|sqlite|sqlserver|mongodb|cockroachdb)"', read(schema))
        db = m.group(1) if m else None
    return {
        **node_scan(root, pkg, deps),
        "stack": "node-prisma",
        "db_engine": "postgresql" if db in ("postgresql", "cockroachdb") else db,
        "db_source": rel(root, schema) if schema else None,
        "query_file_globs": ["*schema.prisma", "*repository*.ts", "*repository*.js", "*Repository.ts"],
        "db_env": {"DATABASE_URL": "postgresql://{user}:{password}@{host}:{port}/{db}?connection_limit={pool}&pool_timeout=10"},
        "default_pool": 5,
    }


def detect_typeorm(root):
    pkg, deps = node_pkg(root)
    if pkg is None or "typeorm" not in deps:
        return None
    db = "postgresql" if "pg" in deps else "mysql" if ("mysql2" in deps or "mysql" in deps) else None
    src = next((p for p in walk(root, exts=(".ts", ".js")) if re.search(r"type:\s*['\"](postgres|mysql|mariadb)['\"]", read(p))), None)
    return {
        **node_scan(root, pkg, deps),
        "stack": "node-typeorm",
        "db_engine": db,
        "db_source": rel(root, src) if src else "package.json",
        "query_file_globs": ["*.entity.ts", "*repository*.ts", "*.service.ts", "*Repository.ts"],
        "db_env": {
            "DATABASE_URL": "postgres://{user}:{password}@{host}:{port}/{db}",
            "DB_HOST": "{host}", "DB_PORT": "{port}", "DB_USERNAME": "{user}", "DB_PASSWORD": "{password}",
            "DB_DATABASE": "{db}", "DB_POOL_SIZE": "{pool}",
        },
        "default_pool": 10,
        "score": 11,
    }


# --------------------------------------------------------------------------- django

def detect_django(root):
    manage = root / "manage.py"
    if not manage.exists():
        found = list(walk(root, names={"manage.py"}, limit=5))
        if not found:
            return None
        manage = found[0]
    settings = [p for p in walk(root, names={"settings.py", "base.py", "prod.py", "production.py", "common.py"})
                if p.name == "settings.py" or p.parent.name == "settings"]
    stext = "\n".join(read(p) for p in settings)
    db = None
    if "postgresql" in stext or "postgres" in stext:
        db = "postgresql"
    elif "mysql" in stext:
        db = "mysql"
    elif "sqlite3" in stext:
        db = "sqlite"
    endpoints = []
    for urls in walk(root, names={"urls.py"}):
        t = read(urls)
        for m in re.finditer(r"\b(re_)?path\(\s*r?['\"]([^'\"]*)['\"]\s*,\s*([^,)]+)", t):
            target = m.group(3).strip()
            if target.startswith("include("):
                continue
            endpoints.append({"method": "ANY", "path": "/" + m.group(2).lstrip("^").rstrip("$"),
                              "file": rel(root, urls), "line": line_of(t, m.start()), "view": target})
        for m in re.finditer(r"router\.register\(\s*r?['\"]([^'\"]*)['\"]", t):
            endpoints.append({"method": "ANY", "path": "/" + m.group(1), "file": rel(root, urls),
                              "line": line_of(t, m.start()), "view": "DRF viewset"})
    reqs = "\n".join(read(p) for p in (root / "requirements.txt", root / "pyproject.toml", root / "Pipfile") if p.exists())
    auth = ["session"]
    if re.search(r"simplejwt|PyJWT|djangorestframework-jwt|dj-rest-auth", reqs + stext, re.I):
        auth.append("jwt")
    if re.search(r"allauth|social-auth|authlib", reqs + stext, re.I):
        auth.append("oauth")
    return {
        "stack": "django", "language": "python",
        "build_tool": "poetry" if "[tool.poetry]" in reqs else "pip", "port": 8000,
        "db_engine": db, "db_source": rel(root, settings[0]) if settings else None,
        "endpoints": endpoints, "auth_kinds": auth,
        "run_command": "gunicorn <project>.wsgi", "manage_py": rel(root, manage),
        "query_file_globs": ["*models.py", "*managers.py", "*querysets.py", "*serializers.py"],
        "db_env": {
            "DATABASE_URL": "postgres://{user}:{password}@{host}:{port}/{db}",
            "DB_HOST": "{host}", "DB_PORT": "{port}", "DB_NAME": "{db}", "DB_USER": "{user}", "DB_PASSWORD": "{password}",
        },
        "default_pool": None,
        "default_env": {"DEBUG": "False", "DJANGO_DEBUG": "False", "ALLOWED_HOSTS": "*"},
        "score": 10,
    }


# --------------------------------------------------------------------------- fastapi + sqlalchemy

FASTAPI_ROUTE = re.compile(r"@(\w+)\.(get|post|put|delete|patch)\(\s*['\"]([^'\"]*)['\"]")


def detect_fastapi(root):
    reqs = "\n".join(read(p) for p in (root / "requirements.txt", root / "pyproject.toml", root / "Pipfile") if p.exists())
    if not re.search(r"^\s*['\"]?fastapi\b", reqs, re.I | re.M):
        return None
    endpoints, port, db, src_db = [], 8000, None, None
    prefixes = {}
    for src in walk(root, exts=(".py",)):
        t = read(src)
        for m in re.finditer(r"(\w+)\s*=\s*APIRouter\(\s*prefix\s*=\s*['\"]([^'\"]*)['\"]", t):
            prefixes[m.group(1)] = m.group(2)
        for m in FASTAPI_ROUTE.finditer(t):
            endpoints.append({"method": m.group(2).upper(), "path": join_path(prefixes.get(m.group(1), ""), m.group(3)),
                              "file": rel(root, src), "line": line_of(t, m.start())})
        if db is None and re.search(r"postgresql(\+\w+)?://|create_engine|asyncpg|psycopg", t):
            db, src_db = "postgresql", rel(root, src)
    if db is None and re.search(r"psycopg|asyncpg", reqs, re.I):
        db = "postgresql"
    is_async = bool(re.search(r"asyncpg|create_async_engine", reqs + "".join(read(p) for p in walk(root, exts=(".py",), limit=400))))
    auth = []
    if re.search(r"pyjwt|python-jose|fastapi-users|authlib|jwt", reqs, re.I):
        auth.append("jwt")
    if re.search(r"authlib|oauth", reqs, re.I):
        auth.append("oauth")
    driver = "postgresql+asyncpg" if is_async else "postgresql+psycopg"
    return {
        "stack": "fastapi", "language": "python", "framework": "fastapi",
        "build_tool": "poetry" if "[tool.poetry]" in reqs else "pip", "port": port,
        "db_engine": db, "db_source": src_db, "endpoints": endpoints, "auth_kinds": auth,
        "run_command": "uvicorn app.main:app",
        "query_file_globs": ["*models.py", "*crud.py", "*repository.py", "*repositories/*.py", "*services/*.py"],
        "db_env": {
            "DATABASE_URL": driver + "://{user}:{password}@{host}:{port}/{db}",
            "DB_POOL_SIZE": "{pool}",
        },
        "default_pool": 5,
        "default_env": {},
        "score": 10,
    }


# --------------------------------------------------------------------------- generic (any other stack)

LANG_MARKERS = [("go.mod", "go"), ("Cargo.toml", "rust"), ("Gemfile", "ruby"), ("composer.json", "php"),
                ("mix.exs", "elixir"), ("build.gradle", "jvm"), ("build.gradle.kts", "jvm"), ("pom.xml", "jvm"),
                ("package.json", "node"), ("pyproject.toml", "python"), ("requirements.txt", "python")]
GENERIC_ROUTES = [
    # Go net/http 1.22 patterns and classic HandleFunc
    re.compile(r"""\.(?:HandleFunc|Handle)\(\s*"(?:(GET|POST|PUT|DELETE|PATCH)\s+)?(/[^"]*)\""""),
    # gin / echo / chi / fiber / express-like:  r.GET("/x"  e.POST("/x"  app.get('/x'
    re.compile(r"""\b\w+\.(GET|POST|PUT|DELETE|PATCH|Get|Post|Put|Delete|Patch|get|post|put|delete|patch)\(\s*["'`](/[^"'`]*)["'`]"""),
    # Rails / Laravel style routes files:  get '/x'   Route::get('/x'
    re.compile(r"""^\s*(?:Route::)?(get|post|put|delete|patch)\s*\(?\s*['"](/[^'"]*)['"]""", re.M),
]


def detect_generic(root):
    """Fallback for any stack: enough to build and wire the app; the agent fills in the rest."""
    lang = next((l for marker, l in LANG_MARKERS if (root / marker).exists()), None)
    if not lang and any(root.glob("*.csproj")):
        lang = "dotnet"
    port = None
    df = next((root / n for n in ("Dockerfile", "dockerfile", "Dockerfile.prod") if (root / n).exists()), None)
    if df:
        m = re.search(r"^\s*EXPOSE\s+(\d+)", read(df), re.M | re.I)
        port = int(m.group(1)) if m else None
    exts = (".go", ".rs", ".rb", ".php", ".ex", ".java", ".kt", ".cs", ".js", ".ts", ".py")
    endpoints, db, mentions = [], None, ""
    for src in walk(root, exts=exts, limit=5000):
        t = read(src)
        mentions += t[:20000] if db is None else ""
        for rx in GENERIC_ROUTES:
            for m in rx.finditer(t):
                method = (m.group(1) or "ANY").upper()
                endpoints.append({"method": method, "path": m.group(2), "file": rel(root, src), "line": line_of(t, m.start())})
        if port is None:
            m = re.search(r"""(?:PORT['"]?\s*[,:]\s*['"]|:)(\d{4,5})['"]""", t)
            if m and int(m.group(1)) not in DATASTORE_PORTS:
                port = int(m.group(1))
    deps = "\n".join(read(root / n) for n in ("go.mod", "Cargo.toml", "Gemfile", "composer.json", "package.json",
                                               "requirements.txt", "pyproject.toml", "pom.xml", "build.gradle") if (root / n).exists())
    blob = deps + mentions
    if re.search(r"postgres|pgx|lib/pq|psycopg|\bpg\b|npgsql|sqlx.*postgres|diesel.*postgres", blob, re.I):
        db = "postgresql"
    elif re.search(r"mysql|mariadb", blob, re.I):
        db = "mysql"
    auth = ["jwt"] if re.search(r"jwt|jose", blob, re.I) else []
    seen, uniq = set(), []
    for e in endpoints:
        k = (e["method"], e["path"])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return {
        "stack": "generic", "language": lang or "unknown", "framework": None, "build_tool": None,
        "port": port or 8080, "db_engine": db, "db_source": None, "endpoints": uniq, "auth_kinds": auth,
        "run_command": None,
        "query_file_globs": ["*repo*", "*repository*", "*dao*", "*store*", "*model*", "*query*", "*queries*", "*.sql"],
        "db_env": {
            "DATABASE_URL": "postgres://{user}:{password}@{host}:{port}/{db}?sslmode=disable",
            "DB_HOST": "{host}", "DB_PORT": "{port}", "DB_NAME": "{db}", "DB_USER": "{user}", "DB_PASSWORD": "{password}",
            "PGHOST": "{host}", "PGPORT": "{port}", "PGDATABASE": "{db}", "PGUSER": "{user}", "PGPASSWORD": "{password}",
        },
        "default_pool": None, "default_env": {}, "score": 1,
    }


# --------------------------------------------------------------------------- env scan

DB_VAR = re.compile(r"^\s*(?:export\s+)?([A-Z0-9_]*(?:DATABASE|DB|POSTGRES|PG|JDBC|DATASOURCE)[A-Z0-9_]*)\s*=\s*(.+)$", re.M)


def scan_env_hosts(root):
    warnings = []
    files = [p for p in root.iterdir() if p.is_file() and (p.name.startswith(".env") or p.name.endswith(".env"))]
    files += list(walk(root, names={"application.yml", "application.yaml", "application.properties", "settings.py"}, limit=200))
    seen = set()
    for f in files:
        t = read(f)
        candidates = [m.group(2) for m in DB_VAR.finditer(t)]
        candidates += re.findall(r"(?:jdbc:)?postgres(?:ql)?://[^\s'\"]+", t)
        candidates += re.findall(r"['\"]HOST['\"]\s*:\s*['\"]([^'\"]+)['\"]", t)
        for v in candidates:
            v = v.strip().strip("'\"")
            if "${" in v or v.startswith("$"):  # env placeholder like ${DB_HOST:localhost}: resolved at runtime, not a host
                v = re.sub(r"\$\{[^}:]*:?([^}]*)\}", r"\1", v)  # keep only the default value, if any
                if not v or v.startswith("$"):
                    continue
            host = url_host(v) or (v if re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", v, re.I) else None)
            if host and looks_production(host) and (f.name, host) not in seen:
                seen.add((f.name, host))
                warnings.append(f"{rel(root, f)} references a non-local DB host '{host}'. catchme never connects to it; "
                                f"confirm with the user before going further.")
    return warnings


SERVICE_HINTS = {
    "redis": r"\bREDIS_URL\b|go-redis|redis-py|\bioredis\b|\bredis\b['\"]|jedis|lettuce|spring-boot-starter-data-redis|django-redis",
    "kafka": r"\bKAFKA_|kafka-go|kafkajs|confluent[-_]kafka|spring-kafka|sarama",
    "rabbitmq": r"\bAMQP_URL\b|\bRABBITMQ_|amqplib|\bpika\b|spring-boot-starter-amqp|amqp091",
    "mongodb": r"\bMONGO(DB)?_URL\b|mongoose|pymongo|mongo-driver|spring-boot-starter-data-mongodb",
    "elasticsearch": r"\bELASTIC(SEARCH)?_URL\b|elasticsearch-py|@elastic/elasticsearch|go-elasticsearch",
    "s3/object storage": r"\bS3_BUCKET\b|aws-sdk.*s3|boto3|@aws-sdk/client-s3|aws-sdk-go.*s3",
}


def scan_services(root):
    """Services the app seems to use besides Postgres — the agent adds them in compose.override.yml."""
    texts = []
    for p in list(walk(root, exts=(".go", ".py", ".js", ".ts", ".java", ".kt", ".rb", ".php", ".rs", ".cs",
                                   ".yml", ".yaml", ".properties", ".toml", ".json", ".mod", ".xml", ".txt"), limit=4000)):
        texts.append(read(p)[:50000])
    blob = "\n".join(texts)
    found = [name for name, rx in SERVICE_HINTS.items() if re.search(rx, blob)]
    return [f"The app seems to use {name}. catchme starts only app + Postgres: add {name} (or a local stand-in) "
            f"in .prod-parity/compose.override.yml and point the app's env at it." for name in found]


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--print", action="store_true", help="print project.json to stdout")
    ap.add_argument("--force", action="store_true", help="overwrite user edits in project.json")
    ap.add_argument("--globs", action="store_true", help="print query_file_globs from project.json (for hooks)")
    args = ap.parse_args()
    if args.globs:
        proj = read_json(pp_dir() / "project.json", default={})
        print("\n".join(proj.get("query_file_globs") or []))
        return

    root = project_root()
    cands = [c for c in (detect_spring(root), detect_typeorm(root), detect_prisma(root),
                          detect_django(root), detect_fastapi(root)) if c]
    out_path = pp_dir() / "project.json"
    previous = read_json(out_path, default={}) if out_path.exists() else {}

    if not cands:
        cands = [detect_generic(root)]
        info("no stack-specific detector matched — using the generic profile (Dockerfile + common DB env vars). "
             "Check project.json: port, health_path, endpoints and app.env are yours to fill in.")
    cands.sort(key=lambda c: (c["score"], len(c["endpoints"])), reverse=True)
    best = cands[0]

    dockerfile = None
    for name in ("Dockerfile", "dockerfile", "Dockerfile.prod", "docker/Dockerfile"):
        if (root / name).exists():
            dockerfile = name
            break
    if (pp_dir() / "app.Dockerfile").exists():
        dockerfile = ".prod-parity/app.Dockerfile"

    warnings = scan_env_hosts(root)
    warnings += scan_services(root)
    if best["db_engine"] and best["db_engine"] != "postgresql":
        warnings.append(f"DB engine '{best['db_engine']}' detected — catchme MVP supports PostgreSQL only.")
    if not dockerfile:
        warnings.append(f"No Dockerfile found. Copy templates/dockerfiles/{best['stack']}.Dockerfile to "
                        f".prod-parity/app.Dockerfile, adjust it, and set app.dockerfile.")

    health = next((e["path"] for e in best["endpoints"] if e["method"] in ("GET", "ANY")
                   and re.fullmatch(r"/?(api/)?(health|healthz|healthcheck|ping|status|actuator/health)/?", e["path"].strip())), "/")
    if not health.startswith("/"):
        health = "/" + health
    login = [e for e in best["endpoints"] if re.search(r"login|signin|sign-in|token|auth", e["path"], re.I)
             and e["method"] in ("POST", "ANY")]
    project = {
        "root": ".",
        "stack": best["stack"],
        "language": best["language"],
        "build_tool": best["build_tool"],
        "framework": best.get("framework"),
        "run_command": best["run_command"],
        "other_candidates": [c["stack"] for c in cands[1:]],
        "db": {"engine": best["db_engine"], "source": best["db_source"]},
        "app": {
            "dockerfile": dockerfile,
            "port": best["port"],
            "host_port": 18080,
            "health_path": health,
            "env": best["default_env"],
            "db_env": best["db_env"],
            "default_pool": best["default_pool"],
        },
        "endpoints": best["endpoints"][:300],
        "auth": {"kinds": best["auth_kinds"], "login_endpoints": login[:10]},
        "query_file_globs": best["query_file_globs"],
        "warnings": warnings,
    }
    if best.get("manage_py"):
        project["manage_py"] = best["manage_py"]

    # Keep the user's edits of the app block (values that differ from what was detected last time),
    # but refresh everything that was only a previous detection result. --force drops all edits.
    detected = json.loads(json.dumps(project["app"]))
    if previous and not args.force and isinstance(previous.get("app"), dict):
        prev_detected = previous.get("_detected_app") or {}
        for k, v in previous["app"].items():
            if k not in prev_detected or prev_detected.get(k) != v:
                project["app"][k] = v
        if previous["app"].get("dockerfile") is None and dockerfile:
            project["app"]["dockerfile"] = dockerfile
    project["_detected_app"] = detected

    write_json(out_path, project)
    if args.print:
        print(json.dumps(project, indent=2, ensure_ascii=False))
    info(f"stack: {project['stack']} ({project['build_tool'] or project['language']}), db: {project['db']['engine']}, "
         f"port: {project['app']['port']}, endpoints: {len(project['endpoints'])}, auth: {','.join(project['auth']['kinds']) or 'none'}")
    for w in warnings:
        info(f"WARNING: {w}")
    info(f"wrote {out_path.relative_to(root)}")


if __name__ == "__main__":
    main()
