#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(rel, old, new):
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{rel}: expected exactly one replacement, got {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


GROUP_MEMBERS = r'''# Exact FQDN-group parser. Group names are compared as fields, so
# domain-list1 can never absorb domain-list10..domain-list19.
group_members()
{
    G="$1"
    FILE="$2"

    awk -v wanted="$G" '
        $1=="object-group" && $2=="fqdn" {
            active=($3==wanted)
            next
        }

        /^!/ {
            active=0
            next
        }

        active && $1=="include" {
            print tolower($2)
        }
    ' "$FILE"
}
'''

replace_once(
    "components/vpn-audit/scripts/vpn-domain-audit.sh",
    "trap cleanup EXIT INT TERM\n\nSTART_EPOCH=$(date +%s)",
    "trap cleanup EXIT INT TERM\n\n\n" + GROUP_MEMBERS + "\nSTART_EPOCH=$(date +%s)",
)
replace_once(
    "components/vpn-audit/scripts/vpn-domain-audit.sh",
    'ndmc -c "show running-config" > "$RUNCFG" 2>/dev/null\n\nWG_GROUPS=',
    'if ! ndmc -c "show running-config" > "$RUNCFG" 2>/dev/null ||\n'
    '   [ ! -s "$RUNCFG" ]; then\n'
    '    echo "ERROR: cannot read running-config"\n'
    '    exit 1\n'
    'fi\n\nWG_GROUPS=',
)
replace_once(
    "components/vpn-audit/scripts/vpn-domain-audit.sh",
    '''for GROUP in $WG_GROUPS; do
    sed -n "/^object-group fqdn $GROUP/,/^!/p" "$RUNCFG" |
    awk -v g="$GROUP" '
        $1=="include" {
            print g "|" $2
        }
    '
done | sort -u | awk -F'|' '!seen[$2]++' > "$TARGETS"''',
    '''for GROUP in $WG_GROUPS; do
    group_members "$GROUP" "$RUNCFG" |
    awk -v g="$GROUP" '{
        print g "|" $0
    }'
done | sort -u | awk -F'|' '!seen[$2]++' > "$TARGETS"''',
)

replace_once(
    "components/vpn-audit/scripts/vpn-night-reconcile.sh",
    '''    rm -f \\
        "$CFG" \\
        "$MEMBERS" \\
        "$ROLLBACK"
        "$POSTSAVE"''',
    '''    rm -f \\
        "$CFG" \\
        "$MEMBERS" \\
        "$ROLLBACK" \\
        "$POSTSAVE"''',
)

RECONCILE_HELPERS = GROUP_MEMBERS + r'''
# Keenetic/ndmc can report a semantic CLI error in text even when the
# process exit code is zero. Treat both transport and semantic errors
# as failures before any change is accepted into rollback state.
ndm_cmd()
{
    CMD="$1"

    NDM_LAST_OUT="$(ndmc -c "$CMD" 2>&1)"
    NDM_LAST_RC=$?

    [ "$NDM_LAST_RC" -eq 0 ] || return 1

    printf '%s\n' "$NDM_LAST_OUT" |
    grep -Eqi 'error\[|syntax error|not found|no such entry' &&
        return 1

    return 0
}


# Returns:
#   0 - membership exists
#   1 - membership is absent
#   2 - running-config could not be verified
membership_state()
{
    G="$1"
    H=$(printf '%s\n' "$2" | tr 'A-Z' 'a-z')
    VCFG="/tmp/vpn-reconcile-verify.$$"

    if ! ndmc -c "show running-config" > "$VCFG" 2>/dev/null ||
       [ ! -s "$VCFG" ]; then
        rm -f "$VCFG"
        return 2
    fi

    if group_members "$G" "$VCFG" | grep -Fxq "$H"; then
        rm -f "$VCFG"
        return 0
    fi

    rm -f "$VCFG"
    return 1
}
'''
replace_once(
    "components/vpn-audit/scripts/vpn-night-reconcile.sh",
    "\nprobe_result()\n{",
    "\n" + RECONCILE_HELPERS + "\nprobe_result()\n{",
)
replace_once(
    "components/vpn-audit/scripts/vpn-night-reconcile.sh",
    '''for G in $WG_GROUPS; do

    sed -n \\
        "/^object-group fqdn $G/,/^!/p" \\
        "$CFG" |
    awk -v g="$G" '
    $1=="include" {
        print g "|" tolower($2)
    }
    ' >> "$MEMBERS"
done''',
    '''for G in $WG_GROUPS; do
    group_members "$G" "$CFG" |
    awk -v g="$G" '{
        print g "|" $0
    }' >> "$MEMBERS"
done''',
)

OLD_TRANSACTION = '''    HOST_REMOVED="/tmp/vpn-reconcile-host-removed.$$"

    : > "$HOST_REMOVED"

    HOST_ERROR=0

    for G in $GROUPS; do

        if ndmc -c \\
           "no object-group fqdn $G include $HOST" \\
           >/dev/null 2>&1; then

            echo "$G|$HOST" >> "$HOST_REMOVED"

        else
            HOST_ERROR=1
            break
        fi

    done

    # --------------------------------------------------------
    # Если хотя бы одно удаление не получилось —
    # возвращаем уже удалённые memberships.
    # --------------------------------------------------------

    if [ "$HOST_ERROR" -ne 0 ]; then

        echo "REMOVE_ERROR: $HOST"
        echo "ROLLBACK_HOST: $HOST"

        while IFS='|' read -r RG RH; do

            [ -n "$RG" ] || continue

            ndmc -c \\
                "object-group fqdn $RG include $RH" \\
                >/dev/null 2>&1 || true

        done < "$HOST_REMOVED"

        rm -f "$HOST_REMOVED"

        ERRORS=$((ERRORS + 1))
        continue
    fi'''

NEW_TRANSACTION = '''    HOST_REMOVED="/tmp/vpn-reconcile-host-removed.$$"

    : > "$HOST_REMOVED"

    HOST_ERROR=0

    for G in $GROUPS; do

        if ! ndm_cmd "no object-group fqdn $G include $HOST"; then
            echo "REMOVE_NDM_ERROR: $G | $HOST | $NDM_LAST_OUT"
            HOST_ERROR=1
            break
        fi

        membership_state "$G" "$HOST"
        MEMBER_RC=$?

        if [ "$MEMBER_RC" -eq 1 ]; then
            echo "$G|$HOST" >> "$HOST_REMOVED"
        else
            echo "REMOVE_VERIFY_ERROR: $G | $HOST | state=$MEMBER_RC"
            HOST_ERROR=1
            break
        fi

    done

    # --------------------------------------------------------
    # Если хотя бы одно удаление не получилось —
    # возвращаем только подтверждённо удалённые memberships.
    # --------------------------------------------------------

    if [ "$HOST_ERROR" -ne 0 ]; then

        echo "REMOVE_ERROR: $HOST"
        echo "ROLLBACK_HOST: $HOST"

        HOST_ROLLBACK_ERRORS=0

        while IFS='|' read -r RG RH; do

            [ -n "$RG" ] || continue

            if ndm_cmd "object-group fqdn $RG include $RH"; then
                membership_state "$RG" "$RH"
                MEMBER_RC=$?

                if [ "$MEMBER_RC" -ne 0 ]; then
                    HOST_ROLLBACK_ERRORS=$((HOST_ROLLBACK_ERRORS + 1))
                fi
            else
                HOST_ROLLBACK_ERRORS=$((HOST_ROLLBACK_ERRORS + 1))
            fi

        done < "$HOST_REMOVED"

        rm -f "$HOST_REMOVED"

        [ "$HOST_ROLLBACK_ERRORS" -eq 0 ] ||
            echo "ROLLBACK_HOST_ERRORS=$HOST_ROLLBACK_ERRORS"

        ERRORS=$((ERRORS + 1))
        continue
    fi'''
replace_once(
    "components/vpn-audit/scripts/vpn-night-reconcile.sh",
    OLD_TRANSACTION,
    NEW_TRANSACTION,
)

replace_once(
    "components/vpn-audit/scripts/vpn-night-reconcile.sh",
    '''    if ndmc -c \\
       "system configuration save" \\
       >/dev/null 2>&1; then''',
    '''    if ndm_cmd "system configuration save"; then''',
)
replace_once(
    "components/vpn-audit/scripts/vpn-night-reconcile.sh",
    '        echo "CONFIG_SAVE_ERROR"',
    '        echo "CONFIG_SAVE_ERROR: $NDM_LAST_OUT"',
)
replace_once(
    "components/vpn-audit/scripts/vpn-night-reconcile.sh",
    '''            if ! ndmc -c \\
               "object-group fqdn $G include $H" \\
               >/dev/null 2>&1; then

                ROLLBACK_ERRORS=$((ROLLBACK_ERRORS + 1))
            fi''',
    '''            if ndm_cmd "object-group fqdn $G include $H"; then
                membership_state "$G" "$H"
                MEMBER_RC=$?

                if [ "$MEMBER_RC" -ne 0 ]; then
                    ROLLBACK_ERRORS=$((ROLLBACK_ERRORS + 1))
                fi
            else
                ROLLBACK_ERRORS=$((ROLLBACK_ERRORS + 1))
            fi''',
)
replace_once(
    "components/vpn-audit/scripts/vpn-night-reconcile.sh",
    '''        ndmc -c \\
            "system configuration save" \\
            >/dev/null 2>&1 || true''',
    '''        ndm_cmd "system configuration save" || true''',
)

TEST = r'''#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "components/vpn-audit/scripts/vpn-domain-audit.sh"
RECONCILE = ROOT / "components/vpn-audit/scripts/vpn-night-reconcile.sh"


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def extract_function(source: str, name: str) -> str:
    pattern = rf"(?ms)^{re.escape(name)}\(\)\n\{{\n.*?^\}}\n"
    match = re.search(pattern, source)
    if not match:
        fail(f"missing shell function: {name}")
    return match.group(0)


def run_shell(script: str, args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
        handle.write("#!/bin/sh\nset -u\n")
        handle.write(script)
        path = handle.name
    try:
        return subprocess.run(
            ["/bin/sh", path, *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
    finally:
        os.unlink(path)


audit_source = AUDIT.read_text(encoding="utf-8")
reconcile_source = RECONCILE.read_text(encoding="utf-8")

for name, source in (("audit", audit_source), ("reconcile", reconcile_source)):
    if 'sed -n "/^object-group fqdn $' in source:
        fail(f"{name} still contains prefix-based FQDN group parsing")

    group_members = extract_function(source, "group_members")

    fixture = """\
dns-proxy
    route object-group domain-list1 Wireguard1
    route object-group domain-list10 Wireguard1
    route object-group domain-list11 Wireguard1
!
object-group fqdn domain-list1
    description Youtube
    include youtube.com
!
object-group fqdn domain-list10
    description GGSEL
    include ggsel.net
!
object-group fqdn domain-list11
    description Supercell
    include clashmini.com
    include supercellstore.com
!
"""

    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as cfg:
        cfg.write(fixture)
        cfg_path = cfg.name

    try:
        result = run_shell(
            group_members
            + '\ngroup_members domain-list1 "$1"\n'
            + 'printf "%s\\n" "---"\n'
            + 'group_members domain-list11 "$1"\n',
            [cfg_path],
        )
    finally:
        os.unlink(cfg_path)

    if result.returncode != 0:
        fail(f"{name} group parser execution failed: {result.stderr.strip()}")

    expected = "youtube.com\n---\nclashmini.com\nsupercellstore.com\n"
    if result.stdout != expected:
        fail(f"{name} group isolation mismatch: {result.stdout!r}")

ndm_cmd = extract_function(reconcile_source, "ndm_cmd")
group_members = extract_function(reconcile_source, "group_members")
membership_state = extract_function(reconcile_source, "membership_state")

if "no such entry" not in ndm_cmd:
    fail("ndm_cmd does not reject Keenetic 'no such entry' semantic errors")
if '"$ROLLBACK" \\\n        "$POSTSAVE"' not in reconcile_source:
    fail("cleanup does not include POSTSAVE in the rm command")

with tempfile.TemporaryDirectory() as td:
    td_path = Path(td)
    fake_ndmc = td_path / "ndmc"

    fake_ndmc.write_text(
        "#!/bin/sh\n"
        "echo 'Network::ObjectGroup: domain-list1: no such entry: clashmini.com'\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_ndmc.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{td}:{env.get('PATH', '')}"

    result = run_shell(ndm_cmd + '\nndm_cmd "test command"\n', [], env)
    if result.returncode == 0:
        fail("ndm_cmd accepted semantic error with process rc=0")

    fake_ndmc.write_text("#!/bin/sh\necho 'ok'\nexit 0\n", encoding="utf-8")
    fake_ndmc.chmod(0o755)

    result = run_shell(ndm_cmd + '\nndm_cmd "test command"\n', [], env)
    if result.returncode != 0:
        fail("ndm_cmd rejected a successful command")

    fixture = td_path / "running-config"
    fixture.write_text(
        "object-group fqdn domain-list1\n"
        "    include youtube.com\n"
        "!\n"
        "object-group fqdn domain-list11\n"
        "    include clashmini.com\n"
        "!\n",
        encoding="utf-8",
    )

    fake_ndmc.write_text(
        "#!/bin/sh\n"
        f"cat '{fixture}'\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_ndmc.chmod(0o755)

    functions = group_members + "\n" + membership_state

    result = run_shell(functions + '\nmembership_state domain-list1 clashmini.com\n', [], env)
    if result.returncode != 1:
        fail(f"membership_state falsely found clashmini.com in domain-list1: rc={result.returncode}")

    result = run_shell(functions + '\nmembership_state domain-list11 clashmini.com\n', [], env)
    if result.returncode != 0:
        fail(f"membership_state missed clashmini.com in domain-list11: rc={result.returncode}")

print("VPN_AUDIT_SAFETY=PASS")
'''
(ROOT / "tests/repository/check-vpn-audit-safety.py").write_text(TEST, encoding="utf-8")

replace_once(
    "tests/repository/run-consistency-checks.sh",
    'python3 tests/repository/check-console-bindings.py || fail "Console bindings"\n',
    'python3 tests/repository/check-console-bindings.py || fail "Console bindings"\n'
    'python3 tests/repository/check-vpn-audit-safety.py || fail "VPN audit safety"\n',
)

print("HOTFIX_APPLIED=1")
