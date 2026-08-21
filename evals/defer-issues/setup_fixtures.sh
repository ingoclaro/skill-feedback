#!/bin/bash
# Rebuild the defer-issues eval fixture repos from scratch.
#
# Usage: ./setup_fixtures.sh [--mechanism rules|mixed] [target-dir]
#
# Every seeded issue's record is issues/issue-<id>.md in both sets; the
# mechanism decides only how it is anchored.
#
#   rules     anchored by a .claude/rules/issue-*.md pointer with paths:
#             globs          -> ./fixtures        (without_skill)
#   mixed     each issue gets the mechanism the hybrid skill should choose for
#             it             -> ./fixtures-hybrid         (with_skill)
#
# (Per-issue `comments` anchoring is still a mechanism — `mixed` picks it for
# the file-specific issues — it just has no whole-fixture-set mode any more.)
#
# The sources and the issue set are defined ONCE below and the mechanism is a
# parameter: the arms of the A/B must see the *same* repo, or a mechanism
# comparison quietly becomes a comparison of two different codebases. Verify
# with `diff -r fixtures fixtures-hybrid` — only the anchors and the records'
# `Affected:` scope may differ.
#
# Fixture issue ids use the reserved `fx-` prefix, and the marker line is
# assembled rather than written literally, so nothing here is mistaken for a
# real pending-issue marker of *this* repo by `git grep` or by
# scripts/check_todo_markers.py.
set -euo pipefail

MECH=rules
TARGET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --mechanism) MECH="${2:?--mechanism needs a value}"; shift 2 ;;
    --mechanism=*) MECH="${1#*=}"; shift ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) TARGET="$1"; shift ;;
  esac
done

HERE="$(cd "$(dirname "$0")" && pwd)"
case "$MECH" in
  rules)    DEFAULT_TARGET="$HERE/fixtures" ;;
  mixed)    DEFAULT_TARGET="$HERE/fixtures-hybrid" ;;
  *) echo "--mechanism must be rules or mixed (got: $MECH)" >&2
     exit 2 ;;
esac
TARGET="${TARGET:-$DEFAULT_TARGET}"
rm -rf "$TARGET"
mkdir -p "$TARGET"

############################################################
# helpers
############################################################

# Which mechanism this issue gets: the global one, except in `mixed`, where the
# argument is the mechanism the hybrid skill is expected to choose for it.
pick() { if [ "$MECH" = mixed ]; then echo "$1"; else echo "$MECH"; fi; }

# The record is the same file whichever mechanism anchors it — only the anchor
# (TODO marker vs .claude/rules pointer) differs.
record_path() {  # <id>
  echo "issues/issue-$1.md"
}

issue_footer() {
cat <<'EOF'
Relevant to what you're doing? Invoke the defer-issues skill to resolve it
properly (gate, fix, verify, close). Not relevant? Note it as pending in
your final report.
EOF
}

rule_footer() {
cat <<'EOF'
Relevant here? Invoke the defer-issues skill to resolve it properly (gate,
fix, verify, close). Not relevant? Note it as pending in your final report.
EOF
}

# The marker keyword is kept in a variable so the literal marker text never
# appears in this file: a literal one is tracked text in *this* repo, which
# made check_todo_markers.py report fixture ids as ignored markers in CI and
# squatted on the local-<n> id space the repo uses for its own issues.
TODO_KEYWORD="TODO"

marker_line() {  # <id> <summary>
  printf '# %s [issue-%s](@/issues/issue-%s.md): %s — fix or flag as pending, never ignore (defer-issues skill)\n' \
    "$TODO_KEYWORD" "$1" "$1" "$2"
}

insert_marker() {  # <file> <anchor-regex> <id> <summary>
  local f=$1 anchor=$2 line
  grep -qE "$anchor" "$f" || {
    echo "insert_marker: anchor /$anchor/ not found in $f" >&2; exit 1; }
  line=$(marker_line "$3" "$4")
  awk -v anchor="$anchor" -v line="$line" '
    !placed && $0 ~ anchor { print line; placed = 1 }
    { print }
  ' "$f" > "$f.tmp"
  mv "$f.tmp" "$f"
}

INDEX=""
add_index() {  # <id> <record-path> <title>
  INDEX="$INDEX- [$1]($2) $3
"
}

# BODY, if set, is the record's description; it is consumed and cleared by the
# next seed_issue call. Unset means "the title, as a sentence".
BODY=""

seed_issue() {  # <mechanism> <id> <file> <anchor-regex|-> <glob> <title> [noindex]
  local mech=$1 id=$2 file=$3 anchor=$4 glob=$5 title=$6 index=${7:-index}
  local body=${BODY:-$title.} affected
  BODY=""
  case "$mech" in
    comments) affected=$file ;;
    rules)    affected=$glob ;;
    *) echo "seed_issue: unknown mechanism: $mech" >&2; exit 1 ;;
  esac
  # The record: always issues/issue-<id>.md, holding the whole issue.
  mkdir -p issues
  { printf '# Pending: %s — %s\n\n' "$id" "$title"
    printf 'Affected: %s\n\n' "$affected"
    printf '%s\n\n' "$body"
    issue_footer
  } > "issues/issue-$id.md"
  # The anchor: a marker at the affected line, or a rule pointing at the record.
  case "$mech" in
    comments)
      [ "$anchor" = "-" ] || insert_marker "$file" "$anchor" "$id" "$title"
      ;;
    rules)
      mkdir -p .claude/rules
      { printf -- '---\npaths:\n  - "%s"\n---\n' "$glob"
        printf '# Pending: %s — %s\n' "$id" "$title"
        printf 'Full record: issues/issue-%s.md\n\n' "$id"
        rule_footer
      } > ".claude/rules/issue-$id.md"
      ;;
  esac
  [ "$index" = noindex ] || add_index "$id" "$(record_path "$id")" "$title"
}

new_repo() {  # <name>
  mkdir -p "$TARGET/$1"
  cd "$TARGET/$1"
  git init -q
  INDEX=""
}

finish_repo() {
  if [ -n "$INDEX" ]; then
    { printf '# Pending issues\n\n'; printf '%s' "$INDEX"; } > ISSUES.md
  fi
  git add -A
  git -c user.email=fixture@example.com -c user.name=Fixture commit -qm "initial commit"
  cd "$TARGET"
}

############################################################
# 1. record-local: clean repo, duplicated retry logic worth deferring
############################################################
new_repo record-local
mkdir -p src
cat > src/foo.py <<'EOF'
import time
import urllib.request


def fetch_profile(user_id):
    for attempt in range(3):
        try:
            return urllib.request.urlopen(f"https://api.example.com/users/{user_id}").read()
        except OSError:
            time.sleep(2 ** attempt)
    raise RuntimeError("fetch_profile failed after retries")


def fetch_orders(user_id):
    for attempt in range(3):
        try:
            return urllib.request.urlopen(f"https://api.example.com/orders?user={user_id}").read()
        except OSError:
            time.sleep(2 ** attempt)
    raise RuntimeError("fetch_orders failed after retries")
EOF
cat > src/bar.py <<'EOF'
def format_price(cents):
    return f"${cents / 100:.2f}"
EOF
finish_repo

############################################################
# 2. surface-resolve: one seeded issue on the file being edited
############################################################
new_repo surface-resolve
mkdir -p src
cat > src/report.py <<'EOF'
def build_report(rows):
    out = []
    for r in rows:
        out.append(f"{r['name']}: {r['total']}")
    return "\n".join(out)


def summarize(rows):
    total = 0
    for r in rows:
        total = total + r["total"]
    return total
EOF
BODY='Rows from the legacy importer sometimes lack the "total" key and
build_report raises KeyError. Fix direction: use r.get("total", 0) in both
functions.'
seed_issue "$(pick comments)" fx-1 src/report.py '^def build_report' \
  'src/report.py' 'build_report crashes on rows missing "total"'
finish_repo

############################################################
# 3. accumulation-cluster: THREE issues that share one root cause.
#    Below any counting threshold, so a run that only counts says "fix
#    piecemeal"; the right answer is a rewrite proposal (there is no money
#    type — amounts are bare floats everywhere).
############################################################
new_repo accumulation-cluster
mkdir -p src/billing
cat > src/billing/invoice.py <<'EOF'
TAX = 0.19


def line_total(line):
    return line["qty"] * line["unit_price"]


def invoice_total(lines):
    subtotal = 0
    for l in lines:
        subtotal += line_total(l)
    return subtotal * (1 + TAX)


def render(lines):
    body = ""
    for l in lines:
        body += l["sku"] + " x" + str(l["qty"]) + " = " + str(line_total(l)) + "\n"
    body += "TOTAL: " + str(invoice_total(lines))
    return body
EOF
seed_issue "$(pick comments)" fx-1 src/billing/invoice.py '^TAX = ' \
  'src/billing/**' 'TAX is a bare float, so every total is binary floating point'
seed_issue "$(pick comments)" fx-2 src/billing/invoice.py '^def line_total' \
  'src/billing/**' 'line_total multiplies money as a float, not an exact decimal'
seed_issue "$(pick comments)" fx-3 src/billing/invoice.py '^def render' \
  'src/billing/**' 'render stringifies float money, so totals print binary artefacts'
finish_repo

############################################################
# 4. audit-drift: index/record/marker inconsistencies to reconcile
############################################################
new_repo audit-drift
mkdir -p src
cat > src/api.py <<'EOF'
def handler(req):
    return {"ok": True}
EOF
# valid record: anchored and indexed
seed_issue "$(pick comments)" fx-1 src/api.py '^def handler' 'src/api.py' \
  'handler lacks input validation'
# orphan record: anchored, but NOT in the index
seed_issue "$(pick comments)" fx-2 src/api.py '^def handler' 'src/api.py' \
  'no request logging' noindex
# stale record: indexed, but nothing anchors it any more — the module it
# covers was deleted, so its glob matches nothing / no marker survives
seed_issue "$(pick rules)" fx-3 src/legacy_sync.py - 'src/legacy_sync.py' \
  'legacy sync retries unbounded'
# dangling index line: no record file behind it
add_index fx-4 "$(record_path fx-4)" 'stale cache never invalidated'
finish_repo

############################################################
# 5. record-architecture: clean repo, package-wide issue worth deferring
############################################################
new_repo record-architecture
mkdir -p src/storage src/web
cat > src/storage/blob.py <<'EOF'
import shutil


def put_blob(key, src_path):
    shutil.copy(src_path, f"/var/data/blobs/{key}")


def get_blob(key, dst_path):
    shutil.copy(f"/var/data/blobs/{key}", dst_path)
EOF
cat > src/storage/cache.py <<'EOF'
import json


def read_cache(key):
    with open(f"/var/data/cache/{key}.json") as f:
        return json.load(f)


def write_cache(key, value):
    with open(f"/var/data/cache/{key}.json", "w") as f:
        json.dump(value, f)
EOF
cat > src/storage/catalog.py <<'EOF'
import sqlite3


def lookup(name):
    con = sqlite3.connect("/var/data/catalog.db")
    try:
        row = con.execute("SELECT id FROM items WHERE name = ?", (name,)).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def register(name):
    con = sqlite3.connect("/var/data/catalog.db")
    try:
        con.execute("INSERT INTO items (name) VALUES (?)", (name,))
        con.commit()
    finally:
        con.close()
EOF
cat > src/web/handlers.py <<'EOF'
from src.storage import blob, cache, catalog


async def serve_item(request):
    item_id = catalog.lookup(request["name"])
    meta = cache.read_cache(str(item_id))
    return {"id": item_id, "meta": meta}
EOF
finish_repo

############################################################
# 6. accumulation-nits: NINE unrelated issues that merely share an address.
#    Over any counting threshold, so a run that only counts says "propose a
#    rewrite"; the right answer is to fix the one at hand and move on.
#    Same invoice.py as accumulation-cluster — only the issue set differs.
############################################################
new_repo accumulation-nits
mkdir -p src/billing
cat > src/billing/invoice.py <<'EOF'
TAX = 0.19


def line_total(line):
    return line["qty"] * line["unit_price"]


def invoice_total(lines):
    subtotal = 0
    for l in lines:
        subtotal += line_total(l)
    return subtotal * (1 + TAX)


def render(lines):
    body = ""
    for l in lines:
        body += l["sku"] + " x" + str(l["qty"]) + " = " + str(line_total(l)) + "\n"
    body += "TOTAL: " + str(invoice_total(lines))
    return body
EOF
seed_issue "$(pick comments)" fx-1 src/billing/invoice.py '^TAX = ' \
  'src/billing/**' 'TAX constant hardcoded; should come from config'
seed_issue "$(pick comments)" fx-2 src/billing/invoice.py '^TAX = ' \
  'src/billing/**' 'module has no docstring'
# fx-3 is the one at hand: it sits on the function the task edits
seed_issue "$(pick comments)" fx-3 src/billing/invoice.py '^def line_total' \
  'src/billing/**' 'line_total assumes qty and unit_price keys exist'
seed_issue "$(pick comments)" fx-4 src/billing/invoice.py '^def line_total' \
  'src/billing/**' 'no unit tests cover line_total'
seed_issue "$(pick comments)" fx-5 src/billing/invoice.py '^def invoice_total' \
  'src/billing/**' 'invoice_total recomputes line_total instead of caching'
seed_issue "$(pick comments)" fx-6 src/billing/invoice.py '^def invoice_total' \
  'src/billing/**' 'single-letter loop variable l is hard to read'
seed_issue "$(pick comments)" fx-7 src/billing/invoice.py '^def render' \
  'src/billing/**' 'the TOTAL: label is not translatable'
seed_issue "$(pick comments)" fx-8 src/billing/invoice.py '^def render' \
  'src/billing/**' 'render output format duplicated in the PDF exporter'
seed_issue "$(pick comments)" fx-9 src/billing/invoice.py '^def render' \
  'src/billing/**' 'type hints missing throughout the module'
finish_repo

echo "$MECH fixtures built in $TARGET: $(ls "$TARGET")"
