// Package exec runs one plan on the router as ONE batch: gate -> check that the affected
// areas did not change since the plan (CAS, right before sending) -> pending record ->
// one RCI request -> one read of the affected areas -> every step proven, or the areas
// put back to their pre-image (compensation), or the operation left «unknown» (blocks new
// ones). The same semantics as the shell executor: success only after the read proves it.
package exec

import (
	"errors"
	"fmt"
	"sort"
	"strings"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/journal"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/ndm"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/plan"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/rci"
)

// Router: narrow reads of areas and one batch of commands.
type Router interface {
	Read(areas []string) (*ndm.Model, error)
	Send(cmds []string) ([]rci.Result, error)
}

type Result struct {
	Outcome journal.Outcome
	Reads   int
	Batches int
}

var ErrChanged = errors.New("exec: the router changed since the plan")

func areasOf(p *plan.Plan) []string {
	seen := map[string]bool{}
	var out []string
	for _, s := range p.Steps {
		if !seen[s.Area] {
			seen[s.Area] = true
			out = append(out, s.Area)
		}
	}
	sort.Strings(out)
	return out
}

func prints(m *ndm.Model, areas []string) map[string]string {
	out := map[string]string{}
	for _, a := range areas {
		out[a] = m.Fingerprint(a)
	}
	return out
}

func equal(a, b map[string]string) bool {
	if len(a) != len(b) {
		return false
	}
	for k, v := range a {
		if b[k] != v {
			return false
		}
	}
	return true
}

// Run executes p, planned from the model planned.
func Run(r Router, j *journal.Journal, op string, planned *ndm.Model, p *plan.Plan) (*Result, error) {
	res := &Result{}
	if len(p.Steps) == 0 {
		// A converged repeat: nothing read again, nothing written, no journal.
		res.Outcome = journal.Outcome{State: "done", Reason: "unchanged"}
		return res, nil
	}
	if err := j.Gate(); err != nil {
		return nil, err
	}
	areas := areasOf(p)
	pre := prints(planned, areas)
	expected := planned.Clone()
	for _, s := range p.Steps {
		if err := expected.Apply(s.Cmd); err != nil {
			return nil, err
		}
	}
	post := prints(expected, areas)
	// CAS right before the batch: only the affected areas, read narrowly.
	now, err := r.Read(readAreas(areas))
	res.Reads++
	if err != nil {
		return nil, fmt.Errorf("exec: read before the batch: %w", err)
	}
	if !equal(prints(now, areas), pre) {
		return res, ErrChanged
	}
	if err := j.Begin(journal.Pending{Op: op, Commands: p.Commands(), Undo: p.Undo(len(p.Steps)), Pre: pre, Post: post}); err != nil {
		return nil, err
	}
	results, sendErr := r.Send(p.Commands())
	res.Batches++
	var notes []string
	for _, x := range results {
		if x.Status == "error" {
			notes = append(notes, x.Command+": "+x.Message)
		}
	}
	after, err := r.Read(readAreas(areas))
	res.Reads++
	if err != nil {
		// No proof either way: unknown, blocks until recovery reads again.
		o := journal.Outcome{State: "unknown", Reason: "no read after the batch: " + err.Error(), Results: notes}
		j.Finish(op, o)
		res.Outcome = o
		return res, nil
	}
	got := prints(after, areas)
	switch {
	case equal(got, post):
		o := journal.Outcome{State: "done", Reason: "verified", Applied: len(p.Steps), Results: notes}
		if sr, err := r.Send([]string{"system configuration save"}); err == nil && len(sr) == 1 && sr[0].Status != "error" {
			o.Saved = true
		}
		res.Batches++
		j.Finish(op, o)
		res.Outcome = o
		return res, nil
	case equal(got, pre):
		why := "not applied"
		if sendErr != nil {
			why += ": " + sendErr.Error()
		}
		o := journal.Outcome{State: "failed", Reason: why, Results: notes}
		j.Finish(op, o)
		res.Outcome = o
		return res, nil
	}
	// Partial: put every affected area back to its pre-image, owned areas only (the
	// plan touched nothing else), then prove it.
	back := restore(after, planned, areas, touchedDoH(p))
	if len(back) > 0 {
		r.Send(back)
		res.Batches++
	}
	again, err := r.Read(readAreas(areas))
	res.Reads++
	if err == nil && equal(prints(again, areas), pre) {
		o := journal.Outcome{State: "failed", Reason: "partial, compensated: " + strings.Join(notes, "; "), Results: notes}
		j.Finish(op, o)
		res.Outcome = o
		return res, nil
	}
	o := journal.Outcome{State: "unknown", Reason: "partial, compensation not proven", Results: notes}
	j.Finish(op, o)
	res.Outcome = o
	return res, nil
}

// readAreas: the router areas behind plan areas.
func readAreas(areas []string) []string {
	need := map[string]bool{}
	for _, a := range areas {
		switch {
		case strings.HasPrefix(a, "group:"):
			need["groups"] = true
		case strings.HasPrefix(a, "route:"):
			need["routes"] = true
		case a == "doh":
			// Smart DNS rows only with the owner's filter profiles (NextDNS) read alongside.
			need["doh"], need["filter"] = true, true
		}
	}
	var out []string
	for k := range need {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// restore: commands taking the current image of the areas back to the pre-image.
// touchedDoH: the Smart DNS rows this plan adds or removes; only they are ever put back
// (the dns-proxy area is shared with the owner's rows, which compensation never touches).
func touchedDoH(p *plan.Plan) map[string]bool {
	out := map[string]bool{}
	for _, s := range p.Steps {
		if s.Area != "doh" {
			continue
		}
		raw := strings.TrimPrefix(strings.TrimPrefix(s.Cmd, "dns-proxy "), "no ")
		out[raw] = true
	}
	return out
}

func restore(cur, pre *ndm.Model, areas []string, doh map[string]bool) []string {
	var cmds []string
	for _, a := range areas {
		kind, name, _ := strings.Cut(a, ":")
		switch kind {
		case "group":
			pg, pok := pre.Groups[name]
			cg, cok := cur.Groups[name]
			if !pok {
				if cok {
					cmds = append(cmds, "no object-group fqdn "+name)
				}
				continue
			}
			have := map[string]bool{}
			if cok {
				for _, d := range cg.Include {
					have[d] = true
				}
			}
			want := map[string]bool{}
			for _, d := range pg.Include {
				want[d] = true
				if !have[d] {
					cmds = append(cmds, "object-group fqdn "+name+" include "+d)
				}
			}
			if cok {
				for _, d := range cg.Include {
					if !want[d] {
						cmds = append(cmds, "no object-group fqdn "+name+" include "+d)
					}
				}
				if cg.Description != pg.Description {
					if pg.Description == "" {
						cmds = append(cmds, "no object-group fqdn "+name+" description")
					} else {
						cmds = append(cmds, "object-group fqdn "+name+" description "+pg.Description)
					}
				}
			}
		case "route":
			for _, r := range cur.RoutesOf(name) {
				if !hasRoute(pre.RoutesOf(name), r) {
					cmds = append(cmds, routeCmd("no ", r))
				}
			}
			for _, r := range pre.RoutesOf(name) {
				if !hasRoute(cur.RoutesOf(name), r) {
					cmds = append(cmds, routeCmd("", r))
				}
			}
		case "doh":
			p := map[string]bool{}
			for _, r := range pre.DoH {
				p[r.Raw] = true
			}
			c := map[string]bool{}
			for _, r := range cur.DoH {
				c[r.Raw] = true
				if !p[r.Raw] && doh[r.Raw] {
					cmds = append(cmds, "dns-proxy no "+r.Raw)
				}
			}
			for _, r := range pre.DoH {
				if !c[r.Raw] && doh[r.Raw] {
					cmds = append(cmds, "dns-proxy "+r.Raw)
				}
			}
		}
	}
	return cmds
}

func hasRoute(rs []ndm.Route, r ndm.Route) bool {
	for _, x := range rs {
		if x == r {
			return true
		}
	}
	return false
}

func routeCmd(no string, r ndm.Route) string {
	c := "dns-proxy " + no + "route object-group " + r.Group + " " + r.Target
	if r.Options != "" {
		c += " " + r.Options
	}
	return c
}
