// Package plan turns a desired state of VWARD's own objects into Keenetic commands, each
// with its inverse and the area it changes. It never emits a command for an object VWARD
// does not own, and refuses outright any command on a protected object (the owner's 8
// Google subnets, the 16 «ip name-server ... on OpkgTun4» rules, NextDNS rows, foreign or
// unknown groups).
package plan

import (
	"fmt"
	"sort"
	"strings"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/ndm"
)

// Group: the desired image of one owned FQDN group.
type Group struct {
	Name        string
	Description string   // "" = leave as is
	Include     []string // complete set
	Target      string   // dns-proxy route target; "" = no route
	Options     string   // "auto"
	Delete      bool     // the group goes away entirely
}

// DoHRow: a Smart DNS row VWARD owns («https upstream URL dnsm on IFACE domain D»).
type DoHRow struct{ URL, Iface, Domain string }

func (r DoHRow) Raw() string {
	s := "https upstream " + r.URL + " dnsm"
	if r.Iface != "" {
		s += " on " + r.Iface
	}
	return s + " domain " + r.Domain
}

// Desired: the whole desired image of what VWARD owns, and what it owns now.
type Desired struct {
	Groups      []Group
	OwnedGroups map[string]bool // groups proven VWARD's (claim or creation journal) or created by this plan
	RouteGroups map[string]bool // the owner's managed lists: their dns-proxy route only
	DoH         []DoHRow        // complete set of VWARD's rows
	OwnedDoH    map[string]bool // raw rows proven VWARD's
	DoHLimit    int
}

type Step struct {
	Area string // "group:NAME", "route:NAME", "doh"
	Cmd  string
	Undo string
}

type Plan struct {
	Steps   []Step
	Refused []string // what was wanted but not planned, with the reason
}

// Protected says whether a command touches what VWARD must never change.
type Protected func(cmd string) (bool, string)

// DefaultProtected: the owner's fixed objects (ROADMAP 4.3/§7): any «ip route» or
// «ip name-server» (VWARD's routing core never writes them), NextDNS rows, OpkgTun4
// name servers.
func DefaultProtected(cmd string) (bool, string) {
	f := strings.Fields(strings.TrimPrefix(cmd, "no "))
	if len(f) >= 2 && f[0] == "ip" && (f[1] == "route" || f[1] == "name-server") {
		return true, "static routes and name servers are never written by the routing core"
	}
	if strings.Contains(strings.ToLower(cmd), "nextdns") {
		return true, "NextDNS rows are the owner's"
	}
	if f2 := strings.Fields(cmd); len(f2) >= 2 && (f2[0] == "system" || f2[0] == "erase" || f2[0] == "copy") && !(len(f2) == 3 && f2[1] == "configuration" && f2[2] == "save") {
		return true, "system commands"
	}
	return false, ""
}

func set(a []string) map[string]bool {
	m := map[string]bool{}
	for _, x := range a {
		m[x] = true
	}
	return m
}

// Build the plan. A group that exists but is not owned is never written: its desired
// change is refused with «foreign». A domain another (foreign) group already routes to a
// different target is refused with «foreign-coverage» (one domain, one assignment).
func Build(cur *ndm.Model, want Desired, protected Protected) (*Plan, error) {
	if protected == nil {
		protected = DefaultProtected
	}
	p := &Plan{}
	for _, area := range []string{"groups", "routes"} {
		if !cur.Read[area] {
			return nil, fmt.Errorf("plan: area %s not read: unknown, no plan", area)
		}
	}
	// Foreign coverage: domain -> foreign group targets.
	foreign := map[string][]string{}
	for _, name := range cur.GroupOrder {
		if want.OwnedGroups[name] {
			continue
		}
		for _, d := range cur.Groups[name].Include {
			for _, r := range cur.RoutesOf(name) {
				foreign[d] = append(foreign[d], name+"->"+r.Target)
			}
		}
	}
	groups := append([]Group(nil), want.Groups...)
	sort.Slice(groups, func(i, j int) bool { return groups[i].Name < groups[j].Name })
	for _, g := range groups {
		if !validName(g.Name) {
			p.Refused = append(p.Refused, g.Name+": invalid group name")
			continue
		}
		have, exists := cur.Groups[g.Name]
		routeOnly := exists && !want.OwnedGroups[g.Name] && want.RouteGroups[g.Name]
		if exists && !want.OwnedGroups[g.Name] && !routeOnly {
			p.Refused = append(p.Refused, g.Name+": foreign")
			continue
		}
		if routeOnly {
			// A managed list: its domains are the owner's; only its route follows the choice.
			if g.Delete || g.Description != "" || !sameSet(have.Include, g.Include) {
				p.Refused = append(p.Refused, g.Name+": route-only (managed list: domains stay the owner's)")
				continue
			}
		}
		if g.Delete {
			if !exists {
				continue
			}
			for _, r := range cur.RoutesOf(g.Name) {
				p.add(Step{"route:" + g.Name, routeCmd("no ", g.Name, r.Target, r.Options), routeCmd("", g.Name, r.Target, r.Options)})
			}
			for _, d := range have.Include {
				p.add(Step{"group:" + g.Name, "no object-group fqdn " + g.Name + " include " + d, "object-group fqdn " + g.Name + " include " + d})
			}
			p.add(Step{"group:" + g.Name, "no object-group fqdn " + g.Name, "object-group fqdn " + g.Name})
			continue
		}
		var curInc []string
		if exists {
			curInc = have.Include
		}
		now, next := set(curInc), set(g.Include)
		var adds []string
		for _, d := range g.Include {
			if now[d] {
				continue
			}
			if fs, ok := foreign[d]; ok && !sameTarget(fs, g.Target) {
				p.Refused = append(p.Refused, d+": foreign-coverage "+strings.Join(fs, ","))
				continue
			}
			adds = append(adds, d)
		}
		sort.Strings(adds)
		if !exists && len(adds) > 0 {
			p.add(Step{"group:" + g.Name, "object-group fqdn " + g.Name, "no object-group fqdn " + g.Name})
		}
		if g.Description != "" && (!exists || have.Description != quote(g.Description) && have.Description != g.Description) && (exists || len(adds) > 0) {
			old := ""
			if exists {
				old = have.Description
			}
			undo := "no object-group fqdn " + g.Name + " description"
			if old != "" {
				undo = "object-group fqdn " + g.Name + " description " + old
			}
			p.add(Step{"group:" + g.Name, "object-group fqdn " + g.Name + " description " + quote(g.Description), undo})
		}
		for _, d := range adds {
			p.add(Step{"group:" + g.Name, "object-group fqdn " + g.Name + " include " + d, "no object-group fqdn " + g.Name + " include " + d})
		}
		var dels []string
		for _, d := range curInc {
			if !next[d] {
				dels = append(dels, d)
			}
		}
		sort.Strings(dels)
		for _, d := range dels {
			p.add(Step{"group:" + g.Name, "no object-group fqdn " + g.Name + " include " + d, "object-group fqdn " + g.Name + " include " + d})
		}
		// Route: exactly one wanted target (or none).
		var routes []ndm.Route
		if exists {
			routes = cur.RoutesOf(g.Name)
		}
		keep := false
		for _, r := range routes {
			if r.Target == g.Target && r.Options == g.Options {
				keep = true
				continue
			}
		}
		if g.Target != "" && !keep && (exists || len(adds) > 0) {
			p.add(Step{"route:" + g.Name, routeCmd("", g.Name, g.Target, g.Options), routeCmd("no ", g.Name, g.Target, g.Options)})
		}
		for _, r := range routes {
			if r.Target == g.Target && r.Options == g.Options {
				continue
			}
			p.add(Step{"route:" + g.Name, routeCmd("no ", g.Name, r.Target, r.Options), routeCmd("", g.Name, r.Target, r.Options)})
		}
	}
	if err := p.doh(cur, want); err != nil {
		return nil, err
	}
	for _, s := range p.Steps {
		for _, c := range []string{s.Cmd, s.Undo} {
			if bad, why := protected(c); bad {
				return nil, fmt.Errorf("plan: protected object in %q: %s", c, why)
			}
			// Allowlist (owner 08.11: NextDNS protected even when it is not found): only these
			// forms on VWARD's own objects ever leave the core; anything else stops the plan.
			if why := allowed(c, want); why != "" {
				return nil, fmt.Errorf("plan: %q is not a command the routing core may send: %s", c, why)
			}
		}
	}
	return p, nil
}

// Check: an error when cmd is not a command the core may send for this desired image.
func Check(cmd string, want Desired) error {
	if why := allowed(cmd, want); why != "" {
		return fmt.Errorf("%s", why)
	}
	return nil
}

func sameSet(a, b []string) bool {
	x, y := set(a), set(b)
	if len(x) != len(y) {
		return false
	}
	for k := range x {
		if !y[k] {
			return false
		}
	}
	return true
}

// allowed: "" when cmd is one of the forms the core may send, on an object it may change.
//
//	[no ]object-group fqdn OWNED [include|exclude DOMAIN | description TEXT]
//	dns-proxy [no ]route object-group OWNED|MANAGED TARGET [auto]
//	dns-proxy [no ]https upstream URL dnsm [on IFACE] domain DOMAIN   (VWARD's rows; never NextDNS)
//	system configuration save
func allowed(cmd string, want Desired) string {
	if cmd == "system configuration save" {
		return ""
	}
	f := strings.Fields(cmd)
	if len(f) > 0 && f[0] == "no" {
		f = f[1:]
	}
	if strings.Contains(strings.ToLower(cmd), "next") {
		return "names NextDNS"
	}
	switch {
	case len(f) >= 3 && f[0] == "object-group" && f[1] == "fqdn":
		if !want.OwnedGroups[f[2]] {
			return "group not VWARD's"
		}
		switch {
		case len(f) == 3:
			return ""
		case len(f) == 5 && (f[3] == "include" || f[3] == "exclude"):
			return ""
		case len(f) >= 4 && f[3] == "description":
			return ""
		}
		return "unknown group command"
	case len(f) >= 2 && f[0] == "dns-proxy":
		g := f[1:]
		if len(g) > 0 && g[0] == "no" {
			g = g[1:]
		}
		switch {
		case len(g) >= 4 && len(g) <= 5 && g[0] == "route" && g[1] == "object-group":
			if !want.OwnedGroups[g[2]] && !want.RouteGroups[g[2]] {
				return "route of a group not VWARD's"
			}
			if len(g) == 5 && g[4] != "auto" {
				return "unknown route option"
			}
			return ""
		case len(g) >= 6 && g[0] == "https" && g[1] == "upstream" && g[3] == "dnsm" && g[len(g)-2] == "domain":
			if len(g) != 6 && !(len(g) == 8 && g[4] == "on") {
				return "unknown Smart DNS row form"
			}
			return ""
		}
		return "dns-proxy command outside routes and VWARD's Smart DNS rows"
	}
	return "outside groups, routes and Smart DNS rows"
}

func (p *Plan) doh(cur *ndm.Model, want Desired) error {
	if want.DoH == nil && want.OwnedDoH == nil {
		return nil
	}
	if !cur.Read["doh"] {
		return fmt.Errorf("plan: area doh not read: unknown, no plan")
	}
	// Smart DNS rows share dns-proxy with the owner's filter profiles (NextDNS): without that part
	// read and recognised, no row is written (not found is not «free to change»).
	if !cur.Read["filter"] {
		for _, r := range want.DoH {
			p.Refused = append(p.Refused, r.Raw()+": dns-filter-unread")
		}
		return nil
	}
	limit := want.DoHLimit
	if limit <= 0 {
		limit = 8
	}
	present := map[string]bool{}
	for _, r := range cur.DoH {
		present[r.Raw] = true
	}
	next := map[string]bool{}
	for _, r := range want.DoH {
		next[r.Raw()] = true
	}
	used := len(cur.DoH)
	// Removals first: they free rows for the additions of the same plan.
	var rm []string
	for _, r := range cur.DoH {
		if want.OwnedDoH[r.Raw] && !next[r.Raw] {
			rm = append(rm, r.Raw)
		}
	}
	sort.Strings(rm)
	for _, raw := range rm {
		p.add(Step{"doh", "dns-proxy no " + raw, "dns-proxy " + raw})
		used--
	}
	var add []string
	for raw := range next {
		if !present[raw] {
			add = append(add, raw)
		}
	}
	sort.Strings(add)
	for _, raw := range add {
		if used >= limit {
			p.Refused = append(p.Refused, raw+": dns-limit")
			continue
		}
		p.add(Step{"doh", "dns-proxy " + raw, "dns-proxy no " + raw})
		used++
	}
	return nil
}

func (p *Plan) add(s Step) { p.Steps = append(p.Steps, s) }

func routeCmd(no, g, t, o string) string {
	c := "dns-proxy " + no + "route object-group " + g + " " + t
	if o != "" {
		c += " " + o
	}
	return c
}

func sameTarget(fs []string, t string) bool {
	for _, f := range fs {
		if !strings.HasSuffix(f, "->"+t) {
			return false
		}
	}
	return true
}

func quote(s string) string { return `"` + s + `"` }

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

// Undo of the first n steps, newest first.
func (p *Plan) Undo(n int) []string {
	var out []string
	for i := n - 1; i >= 0; i-- {
		out = append(out, p.Steps[i].Undo)
	}
	return out
}

// Commands of all steps.
func (p *Plan) Commands() []string {
	out := make([]string, len(p.Steps))
	for i, s := range p.Steps {
		out[i] = s.Cmd
	}
	return out
}
