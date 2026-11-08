package decision

import (
	"sort"
	"strconv"
	"strings"
)

// Audit is vward_routing_audit INTENTS SNAPSHOT (docs/ROUTING_AUDIT_CONTRACT.md).
func Audit(intents, snapshot string) (string, error) {
	type intent struct{ source, domain, scope, target, dns, selected, line string }
	type route struct{ domain, scope, target, dns, owner, permission, line string }
	scopeOK := func(s string) bool { return s == "exact" || s == "subtree" }
	targetOK := func(s string) bool { return s == "ISP" || (strings.HasPrefix(s, "VPN:") && isID(s[4:])) }
	healthOK := func(s string) bool { return s == "available" || s == "unavailable" || s == "unknown" }
	knownOK := func(s string) bool { return s == "known" || s == "unknown" }
	sourceOK := func(s string) bool { return s == "M" || s == "S" || s == "A" }

	invalid := false
	domains := map[string]bool{}
	addDomain := func(s string) {
		domains[s] = true
		if len(domains) > 1024 {
			invalid = true
		}
	}
	intentsBy := map[string]*intent{}
	routes := map[string]*route{}
	toggle, sourceState, hstate := map[string]string{}, map[string]string{}, map[string]string{}
	snapshotCount, generation, snapshotState := 0, "", ""

	scan := func(text string, each func(f []string, line string)) {
		bytes := 0
		for nr, line := range records(text) {
			bytes += len(line) + 1
			if nr+1 > 4096 || bytes > 1048576 {
				invalid = true
				continue
			}
			each(splitTab(line), line)
		}
	}
	scan(intents, func(f []string, line string) {
		if len(f) != 7 || !sourceOK(f[0]) || !isID(f[1]) || !IsDomain(f[2]) || !scopeOK(f[3]) || !targetOK(f[4]) || !isID(f[5]) || !(f[6] == "0" || f[6] == "1") {
			invalid = true
			return
		}
		key := f[0] + ":" + f[1]
		if old, ok := intentsBy[key]; ok {
			if old.line != line {
				invalid = true
			}
			return
		}
		intentsBy[key] = &intent{f[0], f[2], f[3], f[4], f[5], f[6], line}
		addDomain(f[2])
	})
	scan(snapshot, func(f []string, line string) {
		get := func(i int) string {
			if i < len(f) {
				return f[i]
			}
			return ""
		}
		switch get(0) {
		case "snapshot":
			if len(f) != 3 || !isID(f[1]) || !knownOK(f[2]) || snapshotCount > 0 {
				invalid = true
			}
			snapshotCount++
			generation, snapshotState = get(1), get(2)
		case "source":
			if _, dup := toggle[get(1)]; len(f) != 4 || !sourceOK(f[1]) || !(f[2] == "0" || f[2] == "1") || !knownOK(f[3]) || dup {
				invalid = true
			}
			toggle[get(1)], sourceState[get(1)] = get(2), get(3)
		case "health":
			n := get(1)
			if _, dup := hstate[n]; len(f) != 3 || !(n == "DNS" || n == "AGH" || (strings.HasPrefix(n, "VPN:") && targetOK(n))) || !healthOK(f[2]) || dup {
				invalid = true
			}
			hstate[n] = get(2)
		case "route":
			if len(f) != 8 || !isID(f[1]) || !IsDomain(f[2]) || !scopeOK(f[3]) || !targetOK(f[4]) || !isID(f[5]) ||
				!(f[6] == "vward" || f[6] == "manual" || f[6] == "unknown") || !(f[7] == "managed" || f[7] == "reference") ||
				(f[7] == "managed" && f[6] != "vward") {
				invalid = true
				return
			}
			if old, ok := routes[f[1]]; ok {
				if old.line != line {
					invalid = true
				}
				return
			}
			routes[f[1]] = &route{f[2], f[3], f[4], f[5], f[6], f[7], line}
			addDomain(f[2])
		default:
			invalid = true
		}
	})
	_, hasM := toggle["M"]
	_, hasS := toggle["S"]
	_, hasA := toggle["A"]
	_, hasDNS := hstate["DNS"]
	_, hasAGH := hstate["AGH"]
	if snapshotCount != 1 || !hasM || !hasS || !hasA || !hasDNS || !hasAGH {
		invalid = true
	}
	if invalid {
		return "", fail(2, "routing audit: invalid normalized input")
	}
	unknownSnapshot := snapshotState == "unknown"
	for k, v := range toggle {
		if v == "1" && sourceState[k] == "unknown" {
			unknownSnapshot = true
		}
	}
	if len(domains) == 0 {
		return "", nil
	}
	covers := func(parent, sc, child string) bool {
		return parent == child || (sc == "subtree" && len(child) > len(parent) && strings.HasSuffix(child, "."+parent))
	}
	health := func(t string) string {
		if v, ok := hstate[t]; ok {
			return v
		}
		return "unknown"
	}
	sorted := func(m map[string]bool) []string {
		out := make([]string, 0, len(m))
		for k := range m {
			out = append(out, k)
		}
		sort.Strings(out)
		return out
	}
	subset := func(order []string, present map[string]bool) string {
		var out []string
		for _, k := range order {
			if present[k] {
				out = append(out, k)
			}
		}
		if len(out) == 0 {
			return "-"
		}
		return strings.Join(out, ",")
	}
	allWanted, allConfigured, allRights, allIssues, intentKeys := map[string]bool{}, map[string]bool{}, map[string]bool{}, map[string]bool{}, map[string]bool{}
	for k, in := range intentsBy {
		intentKeys[k] = true
		allWanted[in.scope+"@"+in.target+"@"+in.dns] = true
		if strings.HasPrefix(in.target, "VPN:") {
			if hs := health(in.target); hs != "available" {
				allIssues[in.target+":"+hs] = true
			}
		}
	}
	for r, ro := range routes {
		allConfigured[r+"@"+ro.scope+"@"+ro.target+"@"+ro.dns] = true
		allRights[r+"@"+ro.owner+"@"+ro.permission] = true
	}
	if snapshotState == "unknown" {
		allIssues["snapshot:unknown"] = true
	}
	for k, v := range toggle {
		if v == "1" && sourceState[k] == "unknown" {
			allIssues["source:"+k+":unknown"] = true
		}
	}
	if hstate["DNS"] != "available" {
		allIssues["DNS:"+hstate["DNS"]] = true
	}
	if hstate["AGH"] != "available" {
		allIssues["AGH:"+hstate["AGH"]] = true
	}
	order, intentOrder := sorted(domains), sorted(intentKeys)
	wantedOrder, configuredOrder, rightsOrder, issuesOrder := sorted(allWanted), sorted(allConfigured), sorted(allRights), sorted(allIssues)
	var b strings.Builder
	for _, d := range order {
		issues, refs, activeSet, wanted, configured, rights, paths, coverage := map[string]bool{}, map[string]bool{}, map[string]bool{}, map[string]bool{}, map[string]bool{}, map[string]bool{}, map[string]bool{}, map[string]bool{}
		if snapshotState == "unknown" {
			issues["snapshot:unknown"] = true
		}
		for k, v := range toggle {
			if v == "1" && sourceState[k] == "unknown" {
				issues["source:"+k+":unknown"] = true
			}
		}
		duplicates, activeCount, covered := 0, 0, 0
		unavailable, unknownHealth := false, false
		for r, ro := range routes {
			if !covers(ro.domain, ro.scope, d) {
				continue
			}
			configured[r+"@"+ro.scope+"@"+ro.target+"@"+ro.dns] = true
			rights[r+"@"+ro.owner+"@"+ro.permission] = true
			p := ro.target + "@" + ro.dns
			coverage[p+"\x1cexact"] = true
			if ro.scope == "subtree" {
				coverage[p+"\x1csubtree"] = true
			}
			paths[p] = true
		}
		for k, in := range intentsBy {
			if in.domain == d {
				refs[k] = true
			}
			if !covers(in.domain, in.scope, d) || in.selected != "1" || toggle[in.source] != "1" {
				continue
			}
			activeSet[k] = true
			activeCount++
			sig := in.scope + "@" + in.target + "@" + in.dns
			if wanted[sig] {
				duplicates++
			} else {
				wanted[sig] = true
			}
			p := in.target + "@" + in.dns
			paths[p] = true
			if strings.HasPrefix(in.target, "VPN:") {
				hs := health(in.target)
				if hs != "available" {
					issues[in.target+":"+hs] = true
				}
				unavailable = unavailable || hs == "unavailable"
				unknownHealth = unknownHealth || hs == "unknown"
			}
			if coverage[p+"\x1c"+in.scope] {
				covered++
			}
		}
		if activeCount > 0 {
			if hstate["DNS"] != "available" {
				issues["DNS:"+hstate["DNS"]] = true
			}
			if hstate["AGH"] != "available" {
				issues["AGH:"+hstate["AGH"]] = true
			}
			unavailable = unavailable || hstate["DNS"] == "unavailable" || hstate["AGH"] == "unavailable"
			unknownHealth = unknownHealth || hstate["DNS"] == "unknown" || hstate["AGH"] == "unknown"
		}
		var decision, reason string
		switch {
		case len(paths) > 1:
			decision, reason = "unresolved", "conflicting-target-or-dns"
		case unknownSnapshot:
			decision, reason = "unknown", "snapshot-or-source-unknown"
		case activeCount == 0:
			decision, reason = "inactive", "no-active-intent"
		case unavailable:
			decision, reason = "blocked", "dependency-unavailable"
		case unknownHealth:
			decision, reason = "unknown", "dependency-unknown"
		case covered == activeCount:
			decision, reason = "covered", "reuse-existing-coverage"
		default:
			decision, reason = "review", "new-coverage-needed"
		}
		b.WriteString(strings.Join([]string{d, subset(intentOrder, refs), subset(intentOrder, activeSet), subset(wantedOrder, wanted),
			subset(configuredOrder, configured), subset(rightsOrder, rights), strconv.Itoa(duplicates), decision, reason,
			subset(issuesOrder, issues), generation, "unknown"}, "\t") + "\n")
	}
	return b.String(), nil
}
