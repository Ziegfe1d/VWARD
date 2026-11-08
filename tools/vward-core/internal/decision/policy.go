package decision

import "strings"

func isRoute(t, d string) bool {
	return (t == "ISP" || (strings.HasPrefix(t, "VPN:") && isID(t[4:]))) && isID(d)
}

// ServicePolicy is vward_routing_service_policy MODE TARGET DNS REV AUTO_FLOOR EVIDENCE.
func ServicePolicy(mode, target, dns, rev, floor, evidence string) (string, error) {
	type contrib struct{ line string }
	rows := map[string]string{}
	var keys []string
	seen := map[string]bool{}
	pairs := map[string]bool{}
	active, uncertain, bad, header, bytes := false, false, false, false, 0
	add := func(key, src, ref, t, d, state, reason string) {
		rows[key] = strings.Join([]string{"contribution", src, ref, t, d, state, reason}, "\t")
		keys = append(keys, key)
		if state == "active" {
			pairs[t+"\x1c"+d] = true
			active = true
		}
		if state == "unknown" {
			uncertain = true
		}
	}
	for nr, line := range records(evidence) {
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
		get := func(i int) string {
			if i < len(f) {
				return f[i]
			}
			return ""
		}
		k := get(0) + ":" + get(1)
		src := get(0)
		if len(f) != 8 || !(src == "M" || src == "S" || src == "A") || !isRefID(f[1]) || !isRoute(f[2], f[3]) ||
			!(f[4] == "0" || f[4] == "1") || !isRevision(f[6]) || num(f[6]) > num(rev) || seen[k] || (f[0] == "S" && f[1] == "choice") {
			bad = true
			continue
		}
		seen[k] = true
		var state, reason string
		if f[0] == "A" {
			if !(f[5] == "active" || f[5] == "positive" || f[5] == "history" || f[5] == "unknown") ||
				!(f[7] == "bound" || f[7] == "excluded" || f[7] == "unknown") {
				bad = true
				continue
			}
			state, reason = "inactive", "history"
			switch {
			case f[4] == "0":
				reason = "not-selected"
			case f[7] == "excluded":
				reason = "outside-service-scope"
			case f[7] == "unknown" || f[5] == "unknown":
				state, reason = "unknown", "evidence-unknown"
			case f[5] != "history":
				if (f[5] == "positive" && num(f[6]) != num(rev)) || num(f[6]) < num(floor) {
					reason = "stale-auto-evidence"
				} else if mode == "dns" || mode == "isp" || (mode == "vpn" && (f[2] != target || f[3] != dns)) {
					state, reason = "suppressed", "explicit-pin"
				} else {
					state, reason = "active", "auto-evidence"
				}
			}
		} else {
			if f[5] != "explicit" || num(f[6]) != 0 || f[7] != "peer" {
				bad = true
				continue
			}
			if f[4] == "1" {
				state, reason = "active", "peer-explicit"
			} else {
				state, reason = "inactive", "not-selected"
			}
		}
		add(k, f[0], f[1], f[2], f[3], state, reason)
	}
	valid := (mode == "auto" && target == "-" && dns == "-") ||
		(mode == "vpn" && strings.HasPrefix(target, "VPN:") && isID(target[4:]) && dns == "default") ||
		(mode == "dns" && target == "ISP" && isID(dns) && dns != "default") ||
		(mode == "isp" && target == "ISP" && dns == "default")
	if !header || !valid || !isRevision(rev) || !isRevision(floor) || num(floor) > num(rev) || len(keys) > 1024 || bad {
		return "", fail(2, "routing policy: invalid input or limit exceeded")
	}
	if mode != "auto" {
		add("S:choice", "S", "choice", target, dns, "active", "desired-explicit")
	}
	verdict := "inactive"
	switch {
	case len(pairs) > 1:
		verdict = "unresolved"
	case uncertain:
		verdict = "unknown"
	case active:
		verdict = "desired"
	}
	var b strings.Builder
	b.WriteString("policy\t1\t" + verdict + "\tdenied\tunknown\n")
	sortStrings(keys)
	for _, k := range keys {
		b.WriteString(rows[k] + "\n")
	}
	return b.String(), nil
}
