// Package listops: the owner's lists edited from the Panel through the routing core - a domain
// in or out, a list cleared, deleted or merged into another, its route moved to another
// tunnel. Each change is ONE batch through the executor (CAS read, pending record, one RCI
// request, a read that proves it, compensation) instead of the shell's command-by-command
// writes. The owner asked for exactly this change (OwnerCommand): their list is written; the
// protected objects, the DNS filter and AdaptiveAuto (Autopodbor's) stay out of reach.
package listops

import (
	"fmt"
	"strings"
	"time"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/exec"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/journal"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/ndm"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/plan"
)

// Reserved: groups the Panel's list operations never touch.
var Reserved = map[string]bool{"AdaptiveAuto": true}

// Limit of names in one Keenetic group.
const Limit = 300

type Op struct {
	Kind    string // add | remove | clear | delete | merge | route
	Group   string // the list (merge: the one that stays)
	Domain  string // add, remove
	Src     string // merge: the list that goes into Group
	Target  string // route: the interface; "" with NoRoute
	Options string // route: "auto" or ""
	NoRoute bool
}

type Result struct {
	State   string // changed | unchanged | refused | failed | unknown | blocked
	Why     string
	Op      string
	Steps   []string
	Reads   int
	Batches int
}

func validName(s string) bool {
	if s == "" || len(s) > 64 {
		return false
	}
	for _, c := range s {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '_' || c == '-' || c == '.') {
			return false
		}
	}
	return true
}

func validDomain(d string) bool {
	if d == "" || len(d) > 253 || !strings.Contains(d, ".") || strings.HasPrefix(d, ".") || strings.HasSuffix(d, ".") {
		return false
	}
	for _, c := range d {
		if !(c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '-' || c == '.' || c == '_') {
			return false
		}
	}
	return true
}

// route: the group's one route as a plan target ("" none); several routes: refused.
func route(cur *ndm.Model, g string) (string, string, error) {
	rs := cur.RoutesOf(g)
	switch len(rs) {
	case 0:
		return "", "", nil
	case 1:
		return rs[0].Target, rs[0].Options, nil
	}
	return "", "", fmt.Errorf("%s has %d routes: changed by hand only", g, len(rs))
}

// Desired: the image the operation wants, from what the router holds now.
func Desired(cur *ndm.Model, op Op) (plan.Desired, error) {
	want := plan.Desired{OwnedGroups: map[string]bool{}, OwnerCommand: true}
	names := []string{op.Group}
	if op.Kind == "merge" {
		names = append(names, op.Src)
	}
	for _, n := range names {
		if !validName(n) {
			return want, fmt.Errorf("invalid list name %q", n)
		}
		if Reserved[n] {
			return want, fmt.Errorf("%s is not a list the Panel edits", n)
		}
		if cur.Groups[n] == nil {
			return want, fmt.Errorf("list %s not found", n)
		}
		want.OwnedGroups[n] = true
	}
	g := cur.Groups[op.Group]
	inc := append([]string(nil), g.Include...)
	t, o, err := route(cur, op.Group)
	if err != nil {
		return want, err
	}
	d := strings.ToLower(strings.TrimSuffix(op.Domain, "."))
	switch op.Kind {
	case "add":
		if !validDomain(d) {
			return want, fmt.Errorf("invalid domain %q", op.Domain)
		}
		if !contains(inc, d) {
			if len(inc) >= Limit {
				return want, fmt.Errorf("list %s is full (%d)", op.Group, Limit)
			}
			inc = append(inc, d)
		}
	case "remove":
		if !validDomain(d) {
			return want, fmt.Errorf("invalid domain %q", op.Domain)
		}
		inc = without(inc, d)
	case "clear":
		inc = nil
	case "delete":
		want.Groups = []plan.Group{{Name: op.Group, Delete: true}}
		return want, nil
	case "merge":
		if op.Src == op.Group {
			return want, fmt.Errorf("a list does not merge into itself")
		}
		for _, x := range cur.Groups[op.Src].Include {
			if !contains(inc, x) {
				inc = append(inc, x)
			}
		}
		if len(inc) > Limit {
			return want, fmt.Errorf("the merged list would hold %d names (Keenetic keeps %d)", len(inc), Limit)
		}
		want.Groups = append(want.Groups, plan.Group{Name: op.Src, Delete: true})
	case "route":
		if op.NoRoute {
			t, o = "", ""
		} else {
			if !validName(op.Target) {
				return want, fmt.Errorf("invalid interface %q", op.Target)
			}
			t, o = op.Target, op.Options
		}
	default:
		return want, fmt.Errorf("unknown operation %q", op.Kind)
	}
	want.Groups = append(want.Groups, plan.Group{Name: op.Group, Include: inc, Target: t, Options: o})
	return want, nil
}

// Run reads the router, plans and executes one operation.
func Run(r exec.Router, j *journal.Journal, op Op, now time.Time) (*Result, error) {
	res := &Result{Op: fmt.Sprintf("panel-%d-%s", now.UnixNano(), op.Kind)}
	cur, err := r.Read([]string{"groups", "routes"})
	res.Reads++
	if err != nil {
		return nil, fmt.Errorf("read: %w", err)
	}
	want, err := Desired(cur, op)
	if err != nil {
		res.State, res.Why = "refused", err.Error()
		return res, nil
	}
	p, err := plan.Build(cur, want, nil)
	if err != nil {
		res.State, res.Why = "refused", err.Error()
		return res, nil
	}
	if len(p.Refused) > 0 {
		res.State, res.Why = "refused", strings.Join(p.Refused, "; ")
		return res, nil
	}
	for _, s := range p.Steps {
		area := strings.SplitN(s.Area, ":", 2)
		if len(area) != 2 || !want.OwnedGroups[area[1]] {
			return nil, fmt.Errorf("the plan goes beyond the lists asked for: %q", s.Cmd)
		}
		res.Steps = append(res.Steps, s.Cmd)
	}
	if len(p.Steps) == 0 {
		res.State = "unchanged"
		return res, nil
	}
	if err := j.Gate(); err != nil {
		res.State, res.Why = "blocked", err.Error()
		return res, nil
	}
	er, err := exec.Run(r, j, res.Op, cur, p)
	if er != nil {
		res.Reads += er.Reads
		res.Batches += er.Batches
	}
	if err != nil {
		if err == exec.ErrChanged {
			res.State, res.Why = "failed", "the router changed meanwhile: nothing sent, try again"
			return res, nil
		}
		return nil, err
	}
	switch er.Outcome.State {
	case "done":
		res.State = "changed"
	default:
		res.State, res.Why = er.Outcome.State, er.Outcome.Reason
	}
	return res, nil
}

func contains(a []string, s string) bool {
	for _, x := range a {
		if x == s {
			return true
		}
	}
	return false
}

func without(a []string, s string) []string {
	var out []string
	for _, x := range a {
		if x != s {
			out = append(out, x)
		}
	}
	return out
}
