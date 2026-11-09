// Package decision holds the pure routing decisions of architecture B, ported from
// components/runtime/lib/vward-routing-audit.sh byte for byte: the same inputs give the
// same output text and the same refusal codes (2 invalid input, 3 stale revision). The
// parity tests run both on generated cases.
package decision

import (
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// Error carries the shell function's return code.
type Error struct {
	Code int
	Msg  string
}

func (e *Error) Error() string { return e.Msg }

func fail(code int, msg string) *Error { return &Error{code, msg} }

var (
	reService = regexp.MustCompile(`^[a-z0-9][a-z0-9.@_-]*$`)
	reID      = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.:-]*$`)
	reRefID   = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.:@-]*$`)
	reNum     = regexp.MustCompile(`^[0-9]+$`)
	reLabel   = regexp.MustCompile(`^[a-z0-9]([a-z0-9-]*[a-z0-9])?$`)
	reDomain  = regexp.MustCompile(`^[a-z0-9.-]+$`)
)

const maxRev = 2147483647

func isService(s string) bool { return len(s) <= 63 && reService.MatchString(s) }
func isID(s string) bool      { return len(s) <= 64 && reID.MatchString(s) }
func isRefID(s string) bool   { return len(s) <= 64 && reRefID.MatchString(s) }

// awk «s+0»: the leading number of a string ("" and junk -> 0).
func num(s string) float64 {
	s = strings.TrimLeft(s, " \t")
	end := 0
	for end < len(s) && (s[end] >= '0' && s[end] <= '9' || (end == 0 && (s[end] == '-' || s[end] == '+')) || s[end] == '.') {
		end++
	}
	v, _ := strconv.ParseFloat(s[:end], 64)
	return v
}

func isRevision(s string) bool { return reNum.MatchString(s) && num(s) <= maxRev }

// IsDomain: the audit/projection domain grammar (labels 1-63, at least two).
func IsDomain(s string) bool {
	if len(s) > 253 || !reDomain.MatchString(s) {
		return false
	}
	a := strings.Split(s, ".")
	if len(a) < 2 {
		return false
	}
	for _, l := range a {
		if len(l) < 1 || len(l) > 63 || !reLabel.MatchString(l) {
			return false
		}
	}
	return true
}

func validChoice(mode, t, d string) bool {
	switch mode {
	case "auto":
		return t == "-" && d == "-"
	case "vpn":
		return strings.HasPrefix(t, "VPN:") && isID(t[4:]) && d == "default"
	case "dns":
		return t == "ISP" && isID(d) && d != "default"
	}
	return mode == "isp" && t == "ISP" && d == "default"
}

// awk splits on a single tab: empty fields count, so does a trailing tab.
func splitTab(line string) []string { return strings.Split(line, "\t") }

// awk: lines are split on "\n"; a final line without "\n" is still a record; "" -> none.
func records(text string) []string {
	if text == "" {
		return nil
	}
	text = strings.TrimSuffix(text, "\n")
	return strings.Split(text, "\n")
}

// awk «"x" a <= "x" b» under LC_ALL=C: byte order.
func sortStrings(a []string) { sort.SliceStable(a, func(i, j int) bool { return a[i] < a[j] }) }

// Choice is vward_routing_choice LEDGER SID ACTION TARGET DNS EXPECTED_REV.
func Choice(ledger, sid, action, target, dns, expected string) (string, error) {
	type row struct {
		rev            float64
		mode, tgt, pol string
		floor          float64
	}
	rows := map[string]*row{}
	var keys []string
	bad, header, bytes := false, false, 0
	for nr, line := range records(ledger) {
		bytes += len(line) + 1
		if nr+1 > 4096 || bytes > 1048576 {
			bad = true
			continue
		}
		f := splitTab(line)
		if nr == 0 && len(f) == 2 && f[0] == "schema" && f[1] == "1" {
			header = true
			continue
		}
		if len(f) != 7 || f[0] != "service" || !isService(f[1]) || !isRevision(f[2]) ||
			!validChoice(f[3], f[4], f[5]) || !isRevision(f[6]) || num(f[6]) > num(f[2]) {
			bad = true
			continue
		}
		if _, dup := rows[f[1]]; dup {
			bad = true
			continue
		}
		rows[f[1]] = &row{num(f[2]), f[3], f[4], f[5], num(f[6])}
		keys = append(keys, f[1])
	}
	proposed := action
	if action == "on" {
		proposed = "vpn"
	}
	if !header || !isService(sid) || !isRevision(expected) || len(keys) > 1024 ||
		(action != "off" && !validChoice(proposed, target, dns)) ||
		(action == "off" && (target != "-" || dns != "-")) {
		bad = true
	}
	if bad {
		return "", fail(2, "routing choice: invalid input or limit exceeded")
	}
	old, have := rows[sid]
	oldrev := 0.0
	if have {
		oldrev = old.rev
	}
	if oldrev != num(expected) {
		return "", fail(3, "routing choice: stale-revision")
	}
	oldmode, oldtarget, olddns := "auto", "-", "-"
	if have {
		oldmode, oldtarget, olddns = old.mode, old.tgt, old.pol
	}
	if action == "off" {
		if oldmode == "vpn" {
			proposed, target, dns = "auto", "-", "-"
		} else {
			proposed, target, dns = oldmode, oldtarget, olddns
		}
	}
	if proposed != oldmode || target != oldtarget || dns != olddns {
		if oldrev == maxRev || (!have && len(keys) == 1024) {
			return "", fail(2, "routing choice: revision or service limit")
		}
		if !have {
			keys = append(keys, sid)
			rows[sid] = &row{}
		}
		r := rows[sid]
		r.rev, r.mode, r.tgt, r.pol = oldrev+1, proposed, target, dns
		if (oldmode == "dns" || oldmode == "isp") && (proposed == "auto" || proposed == "vpn") {
			r.floor = r.rev
		}
	}
	sortStrings(keys)
	var b strings.Builder
	b.WriteString("schema\t1\n")
	for _, k := range keys {
		r := rows[k]
		b.WriteString(strings.Join([]string{"service", k, awkNum(r.rev), r.mode, r.tgt, r.pol, awkNum(r.floor)}, "\t") + "\n")
	}
	return b.String(), nil
}

// awkNum prints a number as awk's print does for integral values (%d), else %.6g.
func awkNum(v float64) string {
	if v == float64(int64(v)) {
		return strconv.FormatInt(int64(v), 10)
	}
	return strconv.FormatFloat(v, 'g', 6, 64)
}
