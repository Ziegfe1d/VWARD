#!/bin/sh
set -u

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
S92="$ROOT/components/runtime/init.d/S92vward-runtime"
S93="$ROOT/components/runtime/init.d/S93vward-console"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/vward-pid-safety.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
trap 'exit 1' HUP INT TERM

fail(){ echo "FAIL: $*" >&2; exit 1; }

extract_function()
{
    NAME="$1"
    FILE="$2"
    sed -n "/^${NAME}()/,/^}/p" "$FILE"
}

for SPEC in \
    "_vward_pid_valid:$S92" \
    "_vward_pid_start:$S92" \
    "_vward_pid_same_start:$S92" \
    "_sup_identity:$S92" \
    "_sup_signal_same:$S92" \
    "_vward_pidfile_clear_same:$S92" \
    "_sup_stop:$S92" \
    "_console_identity:$S93" \
    "_console_signal_same:$S93" \
    "_console_stop:$S93"
do
    NAME=${SPEC%%:*}
    FILE=${SPEC#*:}
    extract_function "$NAME" "$FILE" > "$WORK/$NAME.sh"
    [ -s "$WORK/$NAME.sh" ] || fail "missing identity-safe helper $NAME"
done

cat "$WORK/_vward_pid_valid.sh" \
    "$WORK/_vward_pid_start.sh" \
    "$WORK/_vward_pid_same_start.sh" \
    "$WORK/_sup_identity.sh" \
    "$WORK/_vward_pidfile_clear_same.sh" > "$WORK/s92-identity.sh"
cat "$WORK/_vward_pid_valid.sh" \
    "$WORK/_vward_pid_start.sh" \
    "$WORK/_vward_pid_same_start.sh" \
    "$WORK/_console_identity.sh" \
    "$WORK/_vward_pidfile_clear_same.sh" > "$WORK/s93-identity.sh"

PROC_ROOT="$WORK/proc"
mkdir -p "$PROC_ROOT/321" "$PROC_ROOT/654"
printf '/opt/bin/sh\0/opt/bin/vward-cron-supervisor.sh\0' > "$PROC_ROOT/321/cmdline"
printf '/opt/sbin/lighttpd\0-f\0/opt/var/run/vward/console-lighttpd.conf\0' > "$PROC_ROOT/654/cmdline"
printf '321 (shell worker (old)) S 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 98765 1\n' > "$PROC_ROOT/321/stat"
printf '654 (lighttpd) S 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 87654 1\n' > "$PROC_ROOT/654/stat"

SUP_DAEMON=/opt/bin/vward-cron-supervisor.sh
. "$WORK/s92-identity.sh"
_sup_identity 321 || fail "supervisor identity rejected its expected cmdline"
_sup_identity 654 && fail "supervisor identity accepted lighttpd"
for BAD in '' 0 1 -1 abc '2 3'; do
    _sup_identity "$BAD" && fail "supervisor identity accepted unsafe PID: $BAD"
done
[ "$(_vward_pid_start 321)" = 98765 ] || fail "supervisor start identity is wrong"
printf '/opt/bin/sh\0/opt/bin/vward-cron-supervisor.sh\0--unexpected\0' > "$PROC_ROOT/321/cmdline"
_sup_identity 321 && fail "supervisor identity accepted extra argv"
printf '/opt/bin/sh\0/opt/bin/vward-cron-supervisor.sh\0' > "$PROC_ROOT/321/cmdline"

LIGHTTPD=/opt/sbin/lighttpd
CONF=/opt/var/run/vward/console-lighttpd.conf
. "$WORK/s93-identity.sh"
_console_identity 654 || fail "Console identity rejected its expected cmdline"
_console_identity 321 && fail "Console identity accepted supervisor"
[ "$(_vward_pid_start 654)" = 87654 ] || fail "Console start identity is wrong"
printf '/opt/sbin/lighttpd\0-D\0-f\0/opt/var/run/vward/console-lighttpd.conf\0' > "$PROC_ROOT/654/cmdline"
_console_identity 654 && fail "Console identity accepted extra argv"
printf '/opt/sbin/lighttpd\0-f\0/opt/var/run/vward/console-lighttpd.conf\0' > "$PROC_ROOT/654/cmdline"

# Stop paths must gate every signal, including escalation, on identity and the
# same process start tick.  These assertions intentionally inspect the small
# lifecycle functions in addition to exercising their identity predicates.
SUP_STOP="$(cat "$WORK/_sup_stop.sh")"
CONSOLE_STOP="$(cat "$WORK/_console_stop.sh")"
printf '%s\n' "$SUP_STOP" | grep -Fq '_sup_identity "$P"' || fail "S92 stop does not verify identity"
printf '%s\n' "$SUP_STOP" | grep -Fq '_vward_pid_start "$P"' || fail "S92 stop does not bind start tick"
printf '%s\n' "$SUP_STOP" | grep -Fq '_sup_signal_same "$P" "$START" TERM' || fail "S92 TERM is not identity-bound"
printf '%s\n' "$CONSOLE_STOP" | grep -Fq '_console_identity "$PID"' || fail "S93 stop does not verify identity"
printf '%s\n' "$CONSOLE_STOP" | grep -Fq '_vward_pid_start "$PID"' || fail "S93 stop does not bind start tick"
printf '%s\n' "$CONSOLE_STOP" | grep -Fq '_console_signal_same "$PID" "$START" TERM' || fail "S93 TERM is not identity-bound"

# Execute both real stop helpers against a stale PID which belongs to the
# other VWARD service.  No signal, including kill -0, may be sent.
KILL_LOG="$WORK/kill.log"
kill(){ printf '%s\n' "$*" >> "$KILL_LOG"; return 0; }
sleep(){ :; }

SUP_PIDFILE="$WORK/supervisor.pid"
SUP_LOCK="$WORK/supervisor.lock"
printf '%s\n' 654 > "$SUP_PIDFILE"
. "$WORK/_sup_stop.sh"
_sup_stop >/dev/null
[ ! -s "$KILL_LOG" ] || fail "S92 stop signalled foreign PID: $(cat "$KILL_LOG")"

PIDFILE="$WORK/console.pid"
printf '%s\n' 321 > "$PIDFILE"
. "$WORK/_console_stop.sh"
_console_stop
[ ! -s "$KILL_LOG" ] || fail "S93 stop signalled foreign PID: $(cat "$KILL_LOG")"

# A same-cmdline replacement with a different start tick must not receive TERM
# or KILL.  Exercise the real signal guards against a deterministic PID reuse.
cat "$WORK/_vward_pid_valid.sh" "$WORK/_vward_pid_start.sh" \
    "$WORK/_vward_pid_same_start.sh" "$WORK/_sup_identity.sh" \
    "$WORK/_sup_signal_same.sh" > "$WORK/s92-signal.sh"
cat "$WORK/_vward_pid_valid.sh" "$WORK/_vward_pid_start.sh" \
    "$WORK/_vward_pid_same_start.sh" "$WORK/_console_identity.sh" \
    "$WORK/_console_signal_same.sh" > "$WORK/s93-signal.sh"
. "$WORK/s92-signal.sh"
: > "$KILL_LOG"
printf '321 (shell worker (new)) S 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 22222 1\n' > "$PROC_ROOT/321/stat"
_sup_signal_same 321 98765 TERM && fail "S92 accepted replaced PID for TERM"
_sup_signal_same 321 98765 KILL && fail "S92 accepted replaced PID for KILL"
[ ! -s "$KILL_LOG" ] || fail "S92 signalled replaced PID"

. "$WORK/s93-signal.sh"
printf '654 (lighttpd new) S 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 33333 1\n' > "$PROC_ROOT/654/stat"
_console_signal_same 654 87654 TERM && fail "S93 accepted replaced PID for TERM"
_console_signal_same 654 87654 KILL && fail "S93 accepted replaced PID for KILL"
[ ! -s "$KILL_LOG" ] || fail "S93 signalled replaced PID"

# Cleanup must preserve a successor PID file when the numeric PID was reused.
. "$WORK/_vward_pidfile_clear_same.sh"
printf '%s\n' 654 > "$PIDFILE"
_vward_pidfile_clear_same "$PIDFILE" 654 87654
[ -f "$PIDFILE" ] || fail "old stop removed successor PID file"

echo RUNTIME_PID_SAFETY=PASS
