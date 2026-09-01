#!/usr/bin/env bash
#
# Apply the Unity Catalog governance layer for the hotel booking demo.
#
# - Creates the four persona groups (idempotent) and adds the current user to
#   hotel_engineer so the operator keeps unmasked, all-rows access.
# - Probes which group-membership function resolves (is_account_group_member vs
#   is_member) and substitutes it into functions.sql.
# - Substitutes {catalog}/{schema} and runs each governance SQL file one statement at
#   a time via the SQL Statements API, continuing on error and printing a summary.
#
# Note: UC object GRANTs require account-level group principals. In a workspace without
# account-admin access the grants.sql step will report PRINCIPAL_DOES_NOT_EXIST; the
# enforcement layer (column masks + row filters, keyed to the same groups via
# is_member) still applies and is demonstrable. constraints.sql is reference-only
# (SDP streaming tables / materialized views reject external constraint DDL).
#
# Usage:
#   PROFILE=serverless_stable_eojwo0 CATALOG=serverless_stable_eojwo0_catalog \
#   SCHEMA=hotel_booking_dev WAREHOUSE=26aa1f864d20b069 governance/apply.sh
#
set -uo pipefail

PROFILE="${PROFILE:-serverless_stable_eojwo0}"
CATALOG="${CATALOG:-serverless_stable_eojwo0_catalog}"
SCHEMA="${SCHEMA:-hotel_booking_dev}"
WAREHOUSE="${WAREHOUSE:-26aa1f864d20b069}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# NB: do not name this GROUPS - that is a bash special array (OS group IDs).
PERSONAS=(hotel_engineer hotel_analyst hotel_mgr_city hotel_mgr_resort)

echo "== Target: ${CATALOG}.${SCHEMA} (profile ${PROFILE}, warehouse ${WAREHOUSE}) =="

group_id() {  # display_name -> id (empty if absent)
  databricks groups list -p "$PROFILE" -o json 2>/dev/null | python3 -c '
import sys,json
d=json.load(sys.stdin); d=d if isinstance(d,list) else d.get("Resources",[])
print(next((g["id"] for g in d if g.get("displayName")==sys.argv[1]),""), end="")' "$1"
}

# ---- 1. Create persona groups (idempotent) --------------------------------------
echo "== Persona groups =="
EXISTING="$(databricks groups list -p "$PROFILE" -o json 2>/dev/null | python3 -c 'import sys,json
d=json.load(sys.stdin); d=d if isinstance(d,list) else d.get("Resources",[])
print("\n".join(g.get("displayName","") for g in d))')"
for g in "${PERSONAS[@]}"; do
  if grep -qx "$g" <<<"$EXISTING"; then
    echo "  exists  ${g}"
  else
    databricks groups create --json "{\"displayName\":\"${g}\"}" -p "$PROFILE" >/dev/null 2>&1 \
      && echo "  created ${g}" || echo "  create failed ${g}"
  fi
done

# ---- 2. Add current user to hotel_engineer --------------------------------------
MY_ID="$(databricks current-user me -p "$PROFILE" -o json | python3 -c 'import sys,json;print(json.load(sys.stdin).get("id",""),end="")')"
MY_NAME="$(databricks current-user me -p "$PROFILE" -o json | python3 -c 'import sys,json;print(json.load(sys.stdin).get("userName",""),end="")')"
ENG_ID="$(group_id hotel_engineer)"
echo "== Operator ${MY_NAME} (id ${MY_ID}) -> hotel_engineer (id ${ENG_ID}) =="
if [[ -n "$MY_ID" && -n "$ENG_ID" ]]; then
  databricks api patch "/api/2.0/preview/scim/v2/Groups/${ENG_ID}" -p "$PROFILE" --json \
    "{\"schemas\":[\"urn:ietf:params:scim:api:messages:2.0:PatchOp\"],\"Operations\":[{\"op\":\"add\",\"path\":\"members\",\"value\":[{\"value\":\"${MY_ID}\"}]}]}" \
    >/dev/null 2>&1 && echo "  membership ensured" || echo "  patch skipped"
fi

# ---- helper: run a single SQL statement via the Statements API ------------------
run_stmt() {
  local esc
  esc="$(python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))' <<<"$1")"
  databricks api post /api/2.0/sql/statements -p "$PROFILE" --json \
    "{\"warehouse_id\":\"${WAREHOUSE}\",\"statement\":${esc},\"wait_timeout\":\"50s\"}" 2>&1
}

# ---- 3. Probe the working group-membership function -----------------------------
MEMBER_FN="is_account_group_member"
PROBE="$(run_stmt "SELECT is_account_group_member('hotel_engineer') AS m" | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("result",{}).get("data_array",[["?"]])[0][0])
except Exception: print("err")')"
if [[ "$PROBE" != "true" ]]; then
  echo "== is_account_group_member did not resolve (got: ${PROBE}); using is_member (workspace groups) =="
  MEMBER_FN="is_member"
else
  echo "== Using is_account_group_member =="
fi

# ---- 4. Apply each governance SQL file, statement by statement -------------------
OK=0; FAIL=0
apply_file() {
  local file="$1"
  echo ""
  echo "== Applying $(basename "$file") =="
  while IFS= read -r -d '' stmt; do
    local label resp state err
    label="$(echo "$stmt" | tr '\n' ' ' | cut -c1-72)"
    resp="$(run_stmt "$stmt")"
    state="$(echo "$resp" | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("status",{}).get("state","?"))
except Exception: print("PARSE_ERR")' 2>/dev/null)"
    if [[ "$state" == "SUCCEEDED" ]]; then
      OK=$((OK+1)); echo "  OK   ${label}"
    else
      FAIL=$((FAIL+1))
      err="$(echo "$resp" | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("status",{}).get("error",{}).get("message",""))
except Exception: print("")' 2>/dev/null | tr '\n' ' ' | cut -c1-150)"
      echo "  FAIL ${label}"
      echo "       ${state}: ${err}"
    fi
  done < <(python3 - "$file" "$CATALOG" "$SCHEMA" "$MEMBER_FN" <<'PY'
import sys
path, cat, sch, member_fn = sys.argv[1:5]
lines=[l for l in open(path).read().splitlines() if not l.lstrip().startswith("--")]
text="\n".join(lines).replace("{catalog}",cat).replace("{schema}",sch).replace("{member_fn}",member_fn)
for raw in text.split(";"):
    s=raw.strip()
    if s: sys.stdout.write(s+"\0")
PY
)
}

apply_file "$DIR/functions.sql"
apply_file "$DIR/comments.sql"
apply_file "$DIR/tags.sql"
apply_file "$DIR/policies.sql"
apply_file "$DIR/grants.sql"   # persona grants: require account-level groups (see note above)

echo ""
echo "== Governance apply complete: ${OK} OK, ${FAIL} FAIL =="
echo "   (constraints.sql is reference-only; grant FAILs are expected without account groups.)"
