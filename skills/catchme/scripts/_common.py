"""Shared helpers for catchme scripts. Standard library only (Python 3.8+)."""
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

HOME = Path(__file__).resolve().parent.parent  # skills/catchme
PP_NAME = ".prod-parity"


def project_root():
    return Path(os.environ.get("CATCHME_PROJECT_IN") or os.getcwd()).resolve()


def pp_dir():
    return project_root() / PP_NAME


def info(msg):
    print(f"[catchme] {msg}", file=sys.stderr)


def die(msg, code=1):
    print(f"[catchme] error: {msg}", file=sys.stderr)
    sys.exit(code)


def read_json(path, default=None):
    p = Path(path)
    if not p.exists():
        if default is not None:
            return default
        die(f"missing file: {p}")
    text = p.read_text().strip()
    if not text:
        if default is not None:
            return default
        die(f"empty file: {p}")
    return json.loads(text)


def write_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_yaml(path, default=None):
    p = Path(path)
    if not p.exists():
        if default is not None:
            return default
        die(f"missing file: {p}")
    try:
        data = load_yaml(p.read_text())
    except ValueError as e:
        die(f"{p}: {e}")
    return data if data is not None else (default if default is not None else {})


def write_yaml(path, data, header=""):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(header + dump_yaml(data))


# --------------------------------------------------------------------------- safety

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "db", "toxiproxy", "app",
               "host.docker.internal", "postgres", "mock-oauth2"}
PROD_HINT = re.compile(
    r"(rds\.amazonaws\.com|\.rds\.|cloudsql|googleapis|database\.azure|database\.windows\.net|"
    r"supabase\.(co|com)|neon\.tech|psdb\.cloud|aivencloud|elephantsql|cockroachlabs|render\.com|"
    r"railway\.app|herokuapp|\bprod\b|production)", re.I)


def url_host(url):
    if not url:
        return None
    u = url.strip()
    if u.startswith("jdbc:"):
        u = u[5:]
    if "://" not in u:
        return None
    try:
        return urlsplit(u).hostname
    except ValueError:
        return None


def is_local_host(host):
    if not host:
        return True
    h = host.lower()
    return (h in LOCAL_HOSTS or h.startswith("127.") or h.endswith(".localhost")
            or h.endswith(".test") or h.endswith(".local"))


def looks_production(host):
    return bool(host) and (not is_local_host(host) or bool(PROD_HINT.search(host)))


# --------------------------------------------------------------------------- mini YAML
# Supports the subset catchme writes and documents: nested maps, lists (of scalars or maps),
# block scalars (| |- >), flow lists/maps, quoted strings, comments, ints/floats/bools/null.

def _strip_comment(line):
    out, q = [], None
    for idx, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
        elif ch in ("'", '"'):
            # only a quote at a token start opens a string
            if idx == 0 or line[idx - 1] in " \t:[{,-":
                q = ch
        elif ch == "#" and (idx == 0 or line[idx - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


_KEY_RE = re.compile(r'^("(?:[^"\\]|\\.)*"|\'(?:[^\']|\'\')*\'|[^\'"\[\]{}#][^:]*?)\s*:(?:\s+(.*)|)$')


def _split_key(s, lineno=None):
    m = _KEY_RE.match(s)
    if not m:
        raise ValueError(f"line {lineno}: expected 'key: value', got: {s}")
    key = m.group(1).strip()
    if key[:1] in ("'", '"'):
        key = parse_scalar(key)
    return key, (m.group(2) or "").strip()


def _is_map_entry(s):
    return s[:1] not in ("[", "{") and bool(_KEY_RE.match(s))


def _split_flow(s):
    parts, depth, q, cur = [], 0, None, []
    for ch in s:
        if q:
            cur.append(ch)
            if ch == q:
                q = None
            continue
        if ch in ("'", '"'):
            q = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


_INT = re.compile(r"^[-+]?\d+$")
_FLOAT = re.compile(r"^[-+]?(\d+\.\d*|\.\d+|\d+(\.\d*)?[eE][-+]?\d+)$")


def parse_scalar(s):
    s = s.strip()
    if s == "":
        return None
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return s[1:-1]
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("''", "'")
    if s[0] == "[" and s[-1] == "]":
        return [parse_scalar(x) for x in _split_flow(s[1:-1])]
    if s[0] == "{" and s[-1] == "}":
        d = {}
        for part in _split_flow(s[1:-1]):
            if ":" not in part:
                raise ValueError(f"bad flow map entry: {part}")
            k, v = part.split(":", 1)
            d[parse_scalar(k)] = parse_scalar(v)
        return d
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "~"):
        return None
    if _INT.match(s):
        return int(s)
    if _FLOAT.match(s):
        return float(s)
    return s


class _Parser:
    def __init__(self, text):
        self.lines = text.replace("\t", "  ").splitlines()
        self.i = 0

    def peek(self):
        while self.i < len(self.lines):
            raw = _strip_comment(self.lines[self.i])
            st = raw.strip()
            if st == "" or st == "---":
                self.i += 1
                continue
            return len(raw) - len(raw.lstrip(" ")), st
        return None

    def block(self, indent):
        p = self.peek()
        if p is None or p[0] < indent:
            return None
        if p[1] == "-" or p[1].startswith("- "):
            return self.seq(p[0])
        return self.mapping(p[0])

    def mapping(self, indent):
        out = {}
        while True:
            p = self.peek()
            if p is None or p[0] < indent:
                break
            ind, s = p
            if ind > indent:
                raise ValueError(f"line {self.i + 1}: unexpected indentation")
            if s == "-" or s.startswith("- "):
                break
            key, rest = _split_key(s, self.i + 1)
            self.i += 1
            out[key] = self.value(rest, indent)
        return out

    def value(self, rest, indent):
        if rest[:1] in ("|", ">") and re.match(r"^[|>][-+]?$", rest):
            return self.block_scalar(indent, rest)
        if rest == "":
            p = self.peek()
            if p and (p[0] > indent or (p[0] == indent and (p[1] == "-" or p[1].startswith("- ")))):
                return self.block(p[0])
            return None
        return parse_scalar(rest)

    def block_scalar(self, indent, style):
        collected, bi = [], None
        while self.i < len(self.lines):
            raw = self.lines[self.i].rstrip("\n")
            if raw.strip() == "":
                collected.append("")
                self.i += 1
                continue
            ind = len(raw) - len(raw.lstrip(" "))
            if ind <= indent:
                break
            if bi is None:
                bi = ind
            collected.append(raw[bi:] if ind >= bi else raw.lstrip(" "))
            self.i += 1
        while collected and collected[-1] == "":
            collected.pop()
        if style.startswith(">"):
            text = " ".join(x for x in collected if x)
        else:
            text = "\n".join(collected)
        return text if style.endswith("-") else text + "\n"

    def seq(self, indent):
        out = []
        while True:
            p = self.peek()
            if p is None or p[0] != indent or not (p[1] == "-" or p[1].startswith("- ")):
                break
            item = p[1][1:].strip()
            if item == "":
                self.i += 1
                out.append(self.block(indent + 1))
            elif _is_map_entry(item) and not item.startswith(("{", "[")):
                raw = self.lines[self.i]
                pos = raw.index("-")
                self.lines[self.i] = raw[:pos] + " " + raw[pos + 1:]
                out.append(self.mapping(self.peek()[0]))
            else:
                self.i += 1
                out.append(parse_scalar(item))
        return out


def load_yaml(text):
    parser = _Parser(text)
    result = parser.block(0)
    if parser.peek() is not None:
        raise ValueError(f"line {parser.i + 1}: could not parse")
    return result


_PLAIN_SAFE = re.compile(r"^[A-Za-z0-9_./@()+-][A-Za-z0-9_ ./@()+=,-]*$")


def _fmt_scalar(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return repr(v) if isinstance(v, float) else str(v)
    s = str(v)
    if (_PLAIN_SAFE.match(s) and not s.endswith(" ") and parse_scalar(s) == s
            and ": " not in s and " #" not in s and not s.startswith("- ")):
        return s
    return json.dumps(s, ensure_ascii=False)


def dump_yaml(obj, indent=0):
    pad = " " * indent
    lines = []
    if isinstance(obj, dict):
        if not obj:
            return pad + "{}\n"
        for k, v in obj.items():
            key = _fmt_scalar(k)
            if isinstance(v, dict) and v:
                lines.append(f"{pad}{key}:\n" + dump_yaml(v, indent + 2))
            elif isinstance(v, list) and v:
                lines.append(f"{pad}{key}:\n" + dump_yaml(v, indent + 2))
            elif isinstance(v, str) and "\n" in v:
                body = "\n".join((pad + "  " + ln) if ln else "" for ln in v.rstrip("\n").split("\n"))
                lines.append(f"{pad}{key}: |\n{body}\n")
            elif isinstance(v, dict):
                lines.append(f"{pad}{key}: {{}}\n")
            elif isinstance(v, list):
                lines.append(f"{pad}{key}: []\n")
            else:
                lines.append(f"{pad}{key}: {_fmt_scalar(v)}\n")
        return "".join(lines)
    if isinstance(obj, list):
        for v in obj:
            if isinstance(v, dict) and v:
                sub = dump_yaml(v, indent + 2)
                lines.append(pad + "- " + sub[indent + 2:])
            elif isinstance(v, list) and v:
                lines.append(f"{pad}-\n" + dump_yaml(v, indent + 2))
            else:
                lines.append(f"{pad}- {_fmt_scalar(v)}\n")
        return "".join(lines)
    return pad + _fmt_scalar(obj) + "\n"


# --------------------------------------------------------------------------- misc

def quote_ident(name):
    return '"' + str(name).replace('"', '""') + '"'


def sql_literal(s):
    return "'" + str(s).replace("'", "''") + "'"


def parse_duration_s(d, default=30):
    if d is None:
        return default
    if isinstance(d, (int, float)):
        return float(d)
    m = re.match(r"^(\d+(?:\.\d+)?)(ms|s|m|h)?$", str(d).strip())
    if not m:
        return default
    n, unit = float(m.group(1)), m.group(2) or "s"
    return n / 1000 if unit == "ms" else n * {"s": 1, "m": 60, "h": 3600}[unit]


def fnum(v, digits=1):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.{digits}f}"
    return f"{v:,}"
