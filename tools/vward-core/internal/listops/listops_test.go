package listops

import (
	"strings"
	"testing"
	"time"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/journal"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/ndm"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/rci"
)

type router struct {
	m       *ndm.Model
	batches [][]string
}

func (f *router) Read([]string) (*ndm.Model, error) { return f.m.Clone(), nil }
func (f *router) Send(cmds []string) ([]rci.Result, error) {
	f.batches = append(f.batches, cmds)
	var out []rci.Result
	for _, c := range cmds {
		if c != "system configuration save" {
			if err := f.m.Apply(c); err != nil {
				return nil, err
			}
		}
		out = append(out, rci.Result{Command: c})
	}
	return out, nil
}

const cfg = `object-group fqdn domain-list0
 description Telegram
 include t.me
 include telegram.org
!
object-group fqdn domain-list5
 include youtube.com
!
object-group fqdn AdaptiveAuto
 include blocked.example.com
!
dns-proxy
 route object-group domain-list0 OpkgTun4 auto
 route object-group domain-list5 OpkgTun4 auto
 route object-group AdaptiveAuto OpkgTun4 auto
!
ip route 8.8.8.0 255.255.255.0 OpkgTun4 auto
`

func run(t *testing.T, op Op) (*Result, *router, *ndm.Model) {
	t.Helper()
	r := &router{m: ndm.ParseRunning(cfg)}
	before := r.m.Clone()
	res, err := Run(r, &journal.Journal{Dir: t.TempDir()}, op, time.Unix(1000, 0))
	if err != nil {
		t.Fatalf("%+v: %v", op, err)
	}
	return res, r, before
}

func cmds(r *router) []string {
	var out []string
	for _, b := range r.batches {
		for _, c := range b {
			if c != "system configuration save" {
				out = append(out, c)
			}
		}
	}
	return out
}

func same(t *testing.T, r *router, before *ndm.Model, areas ...string) {
	t.Helper()
	for _, a := range areas {
		if r.m.Fingerprint(a) != before.Fingerprint(a) {
			t.Fatalf("%s changed", a)
		}
	}
}

var untouched = []string{"group:AdaptiveAuto", "route:AdaptiveAuto"}

func TestAddRemove(t *testing.T) {
	res, r, before := run(t, Op{Kind: "add", Group: "domain-list0", Domain: "Telegram.ME."})
	if res.State != "changed" || strings.Join(cmds(r), "|") != "object-group fqdn domain-list0 include telegram.me" {
		t.Fatalf("add: %+v %q", res, cmds(r))
	}
	same(t, r, before, append(untouched, "group:domain-list5", "route:domain-list0")...)
	res, r, _ = run(t, Op{Kind: "add", Group: "domain-list0", Domain: "t.me"})
	if res.State != "unchanged" || len(r.batches) != 0 {
		t.Fatalf("already there: %+v", res)
	}
	res, r, _ = run(t, Op{Kind: "remove", Group: "domain-list0", Domain: "t.me"})
	if res.State != "changed" || strings.Join(cmds(r), "|") != "no object-group fqdn domain-list0 include t.me" {
		t.Fatalf("remove: %+v %q", res, cmds(r))
	}
}

// The owner adds a domain Autopodbor already routes: added (the owner's choice), AdaptiveAuto
// itself is not touched.
func TestOwnerCommandOverCoverage(t *testing.T) {
	res, r, before := run(t, Op{Kind: "add", Group: "domain-list5", Domain: "blocked.example.com"})
	if res.State != "changed" || len(cmds(r)) != 1 {
		t.Fatalf("%+v %q", res, cmds(r))
	}
	same(t, r, before, untouched...)
}

func TestRouteMove(t *testing.T) {
	res, r, before := run(t, Op{Kind: "route", Group: "domain-list0", Target: "Wireguard1", Options: "auto"})
	got := strings.Join(cmds(r), "|")
	if res.State != "changed" || !strings.Contains(got, "dns-proxy route object-group domain-list0 Wireguard1 auto") || !strings.Contains(got, "dns-proxy no route object-group domain-list0 OpkgTun4") {
		t.Fatalf("route: %+v %q", res, got)
	}
	if len(r.batches) != 2 { // the batch and the save
		t.Fatalf("one batch: %q", r.batches)
	}
	same(t, r, before, append(untouched, "group:domain-list0")...)
	res, r, _ = run(t, Op{Kind: "route", Group: "domain-list0", NoRoute: true})
	if res.State != "changed" || len(r.m.RoutesOf("domain-list0")) != 0 {
		t.Fatalf("no route: %+v", res)
	}
}

func TestClearDeleteMerge(t *testing.T) {
	res, r, _ := run(t, Op{Kind: "clear", Group: "domain-list0"})
	if res.State != "changed" || len(r.m.Groups["domain-list0"].Include) != 0 || len(r.m.RoutesOf("domain-list0")) != 1 {
		t.Fatalf("clear: %+v", res)
	}
	res, r, before := run(t, Op{Kind: "delete", Group: "domain-list5"})
	if res.State != "changed" || r.m.Groups["domain-list5"] != nil || len(r.m.RoutesOf("domain-list5")) != 0 {
		t.Fatalf("delete: %+v", res)
	}
	same(t, r, before, append(untouched, "group:domain-list0", "route:domain-list0")...)
	res, r, before = run(t, Op{Kind: "merge", Src: "domain-list5", Group: "domain-list0"})
	if res.State != "changed" || r.m.Groups["domain-list5"] != nil || !contains(r.m.Groups["domain-list0"].Include, "youtube.com") || len(r.m.RoutesOf("domain-list0")) != 1 {
		t.Fatalf("merge: %+v", res)
	}
	if len(r.batches) != 2 {
		t.Fatalf("merge is one batch: %q", r.batches)
	}
	same(t, r, before, untouched...)
}

func TestRefused(t *testing.T) {
	for _, op := range []Op{
		{Kind: "add", Group: "AdaptiveAuto", Domain: "x.example.com"},
		{Kind: "delete", Group: "AdaptiveAuto"},
		{Kind: "add", Group: "nosuchlist", Domain: "x.example.com"},
		{Kind: "add", Group: "domain-list0", Domain: "bad domain"},
		{Kind: "merge", Src: "domain-list0", Group: "domain-list0"},
		{Kind: "route", Group: "domain-list0", Target: "OpkgTun4; erase"},
		{Kind: "add", Group: "bad name!", Domain: "x.example.com"},
		{Kind: "unknown", Group: "domain-list0"},
	} {
		res, r, _ := run(t, op)
		if res.State != "refused" || len(r.batches) != 0 {
			t.Fatalf("%+v must be refused before anything is sent: %+v", op, res)
		}
	}
}

func TestBlockedJournal(t *testing.T) {
	r := &router{m: ndm.ParseRunning(cfg)}
	j := &journal.Journal{Dir: t.TempDir()}
	j.Begin(journal.Pending{Op: "stuck", Pre: map[string]string{"group:x": "a"}, Post: map[string]string{"group:x": "b"}})
	res, err := Run(r, j, Op{Kind: "add", Group: "domain-list0", Domain: "a.example.com"}, time.Unix(1, 0))
	if err != nil || res.State != "blocked" || len(r.batches) != 0 {
		t.Fatalf("an open operation blocks: %v %+v", err, res)
	}
}
