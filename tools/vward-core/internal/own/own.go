// Package own decides what the routing core may change, with the evidence the shell core keeps
// (vward-console-config.sh): a claim file services/owned/GROUP whose signature equals the group
// now (full), the private journal of an accepted creation of that group by a service transaction
// (service_origin: full), or the owner's explicit «take this list under VWARD's management»
// (managed.GROUP=1 in domain-lists.conf: its route only). Anything else is foreign: never written.
// A name, a description or a catalog match is never evidence.
package own

import (
	"bufio"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"syscall"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/ndm"
)

type Level int

const (
	None  Level = iota // foreign or unknown: no command, ever
	Route              // managed list: its dns-proxy route may change, its domains may not
	Full               // VWARD's own group: domains, description, route, deletion
)

func (l Level) String() string { return [...]string{"none", "route", "full"}[l] }

type Verdict struct {
	Group  string
	Level  Level
	Reason string // claim | provenance | adopted | no-proof | proof-mode | proof-owner | changed-since-claim | group-absent | adaptive
}

// Paths of the shell core's state (defaults of an installed router).
type Paths struct {
	Etc    string // /opt/etc/vward
	Backup string // /opt/var/backups/vward/console-config
}

func Default() Paths {
	return Paths{Etc: "/opt/etc/vward", Backup: "/opt/var/backups/vward/console-config"}
}

func validGroup(g string) bool {
	if g == "" || len(g) > 64 || g == "AdaptiveAuto" {
		return false
	}
	for _, c := range g {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '_' || c == '.' || c == '-') {
			return false
		}
	}
	return true
}

// private: a regular file or directory (not a link) of this user, mode exactly as required.
func private(path string, dir bool, mode os.FileMode) bool {
	st, err := os.Lstat(path)
	if err != nil || st.Mode()&os.ModeSymlink != 0 {
		return false
	}
	if dir != st.IsDir() || (!dir && !st.Mode().IsRegular()) {
		return false
	}
	if s, ok := st.Sys().(*syscall.Stat_t); ok && int(s.Uid) != os.Getuid() {
		return false
	}
	return mode == 0 || st.Mode().Perm() == mode
}

func mine(path string) bool { return private(path, false, 0) }

// Claim: the claim file of the shell core (service_owned).
func Claim(p Paths, m *ndm.Model, g string) (bool, string) {
	if !validGroup(g) {
		return false, "invalid-group"
	}
	f := filepath.Join(p.Etc, "services/owned", g)
	st, err := os.Lstat(f)
	if err != nil {
		return false, "no-proof"
	}
	if !st.Mode().IsRegular() || (st.Mode().Perm() != 0o600 && st.Mode().Perm() != 0o400) {
		return false, "proof-mode"
	}
	if !mine(f) {
		return false, "proof-owner"
	}
	b, err := os.ReadFile(f)
	if err != nil {
		return false, "proof-unreadable"
	}
	sig, ok := m.Signature(g)
	if !ok {
		return false, "group-absent"
	}
	if ndm.CanonicalSignature(string(b)) != sig {
		return false, "changed-since-claim"
	}
	return true, "claim"
}

func readLines(path string) ([]string, bool) {
	f, err := os.Open(path)
	if err != nil {
		return nil, false
	}
	defer f.Close()
	var out []string
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 64*1024), 1<<20)
	for sc.Scan() {
		out = append(out, sc.Text())
	}
	return out, sc.Err() == nil
}

// canonicalBody: a stored group body as service_canonical prints it (description unquoted, sorted).
func canonicalBody(lines []string) string {
	var out []string
	for _, l := range lines {
		if strings.HasPrefix(l, `description "`) && strings.HasSuffix(l, `"`) && len(l) >= 14 {
			if d := l[13 : len(l)-1]; !strings.ContainsAny(d, `"\`) {
				l = "description " + d
			}
		}
		out = append(out, l)
	}
	sort.Strings(out)
	return strings.Join(out, "\n")
}

// Origin: service_origin ID TARGET of the shell core - the one group an accepted service
// transaction created for this service and that is still exactly what it created. "" if none or
// if two transactions name different groups (no guess). skip: groups not to consider (the shell
// reconnects only groups absent from enabled.tsv; as ownership evidence nothing is skipped).
func Origin(p Paths, m *ndm.Model, id, target, defaultTunnel string, skip map[string]bool) string {
	if target == "vpn" {
		target = defaultTunnel
	}
	dirs, _ := filepath.Glob(filepath.Join(p.Backup, "service-transactions.resolved", "txn.*"))
	found := ""
	for _, d := range dirs {
		if !private(d, true, 0o700) {
			continue
		}
		ok := true
		for _, f := range []string{"after.enabled", "resolved", "groups"} {
			if !mine(filepath.Join(d, f)) {
				ok = false
			}
		}
		if !ok {
			continue
		}
		res, _ := readLines(filepath.Join(d, "resolved"))
		accepted := false
		for _, l := range res {
			if l == "state=accepted:partial" || l == "state=committed" {
				accepted = true
			}
		}
		if !accepted {
			continue
		}
		after, _ := readLines(filepath.Join(d, "after.enabled"))
		g := ""
		for _, l := range after {
			f := strings.Split(l, "\t")
			if len(f) == 3 && f[0] == id {
				g = f[1]
			}
		}
		if !validGroup(g) {
			continue
		}
		if skip[g] {
			continue
		}
		for _, f := range []string{"new." + g, "group." + g, "route." + g} {
			if !mine(filepath.Join(d, f)) {
				ok = false
			}
		}
		if !ok {
			continue
		}
		if st, _ := os.Stat(filepath.Join(d, "group."+g)); st == nil || st.Size() != 0 {
			continue
		}
		if st, _ := os.Stat(filepath.Join(d, "route."+g)); st == nil || st.Size() != 0 {
			continue
		}
		groups, _ := readLines(filepath.Join(d, "groups"))
		listed := false
		for _, l := range groups {
			if l == g {
				listed = true
			}
		}
		if !listed {
			continue
		}
		grp, exists := m.Groups[g]
		if !exists {
			continue
		}
		body := canonicalBody(grp.Lines)
		newLines, _ := readLines(filepath.Join(d, "new."+g))
		if body == "" || body != canonicalBody(newLines) {
			continue
		}
		routes := m.RoutesOf(g)
		if len(routes) > 1 || (len(routes) == 1 && !(routes[0].Target == target && routes[0].Options == "auto")) {
			continue
		}
		lf := filepath.Join(p.Etc, "route-engine/domain-lists", g)
		if _, err := os.Lstat(lf); err == nil {
			if !mine(lf) {
				continue
			}
			ll, _ := readLines(lf)
			n, bad := 0, false
			for _, l := range ll {
				switch l {
				case "route=-", "route=-\t-", "route=-\tauto":
					n++
				default:
					bad = true
				}
			}
			if bad || n != 1 {
				continue
			}
		}
		if found != "" && found != g {
			return ""
		}
		found = g
	}
	return found
}

// Managed: managed.GROUP=1 in domain-lists.conf (the owner's confirmed «list-adopt»).
func Managed(p Paths, g string) bool {
	lines, _ := readLines(filepath.Join(p.Etc, "route-engine/domain-lists.conf"))
	v := ""
	for _, l := range lines {
		if k, val, ok := strings.Cut(l, "="); ok && k == "managed."+g {
			v = val
			break
		}
	}
	return v == "1"
}

// Service: the verdict for one enabled service (enabled.tsv: ID, GROUP, PIN).
func Service(p Paths, m *ndm.Model, id, group, pin, defaultTunnel string) Verdict {
	if group == "AdaptiveAuto" {
		return Verdict{group, None, "adaptive"}
	}
	if ok, why := Claim(p, m, group); ok {
		return Verdict{group, Full, why}
	} else if why == "changed-since-claim" || why == "proof-mode" || why == "proof-owner" {
		// A claim that no longer matches is the owner's edit: never overridden by a journal.
		return Verdict{group, None, why}
	}
	target := pin
	if target == "auto" {
		target = "vpn"
	}
	if g := Origin(p, m, id, target, defaultTunnel, nil); g == group {
		return Verdict{group, Full, "provenance"}
	}
	if Managed(p, group) {
		return Verdict{group, Route, "adopted"}
	}
	return Verdict{group, None, "no-proof"}
}
