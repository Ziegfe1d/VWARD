package exec

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/journal"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/ndm"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/plan"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/rci"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/router"
)

// The owner's router in miniature: his own lists, the 8 Google subnets and 16 name
// servers on OpkgTun4, NextDNS, a foreign group, three tunnels.
const ownerCfg = `object-group fqdn domain-list0
    description Telegram
    include t.me
    include telegram.org
!
object-group fqdn domain-list4
    description "Claude AI"
    include claude.ai
!
object-group fqdn AdaptiveAuto
    include adaptive-one.example
!
dns-proxy
    route object-group domain-list0 OpkgTun4 auto
    route object-group domain-list4 OpkgTun4 auto
    route object-group AdaptiveAuto OpkgTun4 auto
    https upstream https://dns.nextdns.io/abc dnsm on ISP domain nextdns.example
!
interface OpkgTun4
!
interface Wireguard1
!
interface OpkgTun2
!
ip route 8.8.4.0 255.255.255.0 OpkgTun4 auto
ip route 8.8.8.0 255.255.255.0 OpkgTun4 auto
ip route 8.34.208.0 255.255.240.0 OpkgTun4 auto
ip route 8.35.192.0 255.255.240.0 OpkgTun4 auto
ip route 23.236.48.0 255.255.240.0 OpkgTun4 auto
ip route 23.251.128.0 255.255.224.0 OpkgTun4 auto
ip route 34.0.0.0 255.254.0.0 OpkgTun4 auto
ip route 35.184.0.0 255.248.0.0 OpkgTun4 auto
ip name-server 8.8.8.8 youtube.com on OpkgTun4
ip name-server 1.1.1.1 youtube.com on OpkgTun4
ip name-server 8.8.8.8 youtu.be on OpkgTun4
ip name-server 1.1.1.1 youtu.be on OpkgTun4
ip name-server 8.8.8.8 googlevideo.com on OpkgTun4
ip name-server 1.1.1.1 googlevideo.com on OpkgTun4
ip name-server 8.8.8.8 ytimg.com on OpkgTun4
ip name-server 1.1.1.1 ytimg.com on OpkgTun4
ip name-server 8.8.8.8 ggpht.com on OpkgTun4
ip name-server 1.1.1.1 ggpht.com on OpkgTun4
ip name-server 8.8.8.8 youtube-nocookie.com on OpkgTun4
ip name-server 1.1.1.1 youtube-nocookie.com on OpkgTun4
ip name-server 8.8.8.8 youtubei.googleapis.com on OpkgTun4
ip name-server 1.1.1.1 youtubei.googleapis.com on OpkgTun4
ip name-server 8.8.8.8 yt3.ggpht.com on OpkgTun4
ip name-server 1.1.1.1 yt3.ggpht.com on OpkgTun4
`

type env struct {
	fake *fakeKeenetic
	r    *router.RCI
	j    *journal.Journal
}

func setup(t *testing.T, cfg string) *env {
	f := newFake(t, cfg)
	return &env{fake: f, r: router.New(rci.New(f.addr(), false), true), j: &journal.Journal{Dir: filepath.Join(t.TempDir(), "journal")}}
}

func (e *env) model(t *testing.T) *ndm.Model {
	m, err := e.r.Read([]string{"groups", "routes", "doh"})
	if err != nil {
		t.Fatal(err)
	}
	return m
}

func (e *env) full(t *testing.T) *ndm.Model {
	m, _, err := e.r.Full()
	if err != nil {
		t.Fatal(err)
	}
	return m
}

var youtube = plan.Group{Name: "domain-list7", Description: "YouTube", Include: []string{"youtube.com", "googlevideo.com", "ytimg.com"}, Target: "OpkgTun4", Options: "auto"}

func run(t *testing.T, e *env, op string, want plan.Desired) (*Result, *plan.Plan, error) {
	t.Helper()
	m := e.model(t)
	p, err := plan.Build(m, want, nil)
	if err != nil {
		t.Fatal(err)
	}
	res, err := Run(e.r, e.j, op, m, p)
	return res, p, err
}

func protectedIntact(t *testing.T, e *env) {
	t.Helper()
	s := e.fake.staticLines()
	if strings.Count(s, "ip route ") != 8 || strings.Count(s, "ip name-server ") != 16 {
		t.Fatalf("protected objects changed:\n%s", s)
	}
	m := e.full(t)
	found := false
	for _, d := range m.DoH {
		if strings.Contains(d.Raw, "nextdns") {
			found = true
		}
	}
	if !found {
		t.Fatal("NextDNS row gone")
	}
}

func TestNarrowEqualsFull(t *testing.T) {
	e := setup(t, ownerCfg)
	n, f := e.model(t), e.full(t)
	for _, a := range []string{"group:domain-list0", "group:domain-list4", "group:AdaptiveAuto", "route:domain-list0", "doh"} {
		if n.Fingerprint(a) != f.Fingerprint(a) {
			t.Fatalf("%s: narrow %q full %q", a, n.Fingerprint(a), f.Fingerprint(a))
		}
	}
}

func TestServiceOnOneBatchVerified(t *testing.T) {
	e := setup(t, ownerCfg)
	want := plan.Desired{Groups: []plan.Group{youtube}, OwnedGroups: map[string]bool{"domain-list7": true}}
	res, p, err := run(t, e, "op1", want)
	if err != nil {
		t.Fatal(err)
	}
	if res.Outcome.State != "done" || !res.Outcome.Saved {
		t.Fatalf("outcome %+v", res.Outcome)
	}
	// One batch for the change, one for the save; two narrow reads (CAS, proof); no full read.
	if res.Batches != 2 || res.Reads != 2 || len(e.fake.batches[0]) != len(p.Steps) || e.fake.fullRead != 0 {
		t.Fatalf("batches=%d reads=%d batch0=%d steps=%d full=%d", res.Batches, res.Reads, len(e.fake.batches[0]), len(p.Steps), e.fake.fullRead)
	}
	m := e.full(t)
	if strings.Join(m.Groups["domain-list7"].Include, ",") != "googlevideo.com,youtube.com,ytimg.com" || len(m.RoutesOf("domain-list7")) != 1 {
		t.Fatalf("not applied: %+v %+v", m.Groups["domain-list7"], m.RoutesOf("domain-list7"))
	}
	protectedIntact(t, e)
	// The repeat: converged, nothing read, nothing written, no journal entry.
	before := len(e.fake.batches)
	res, p, err = run(t, e, "op2", want)
	if err != nil || len(p.Steps) != 0 || res.Reads != 0 || res.Batches != 0 || len(e.fake.batches) != before {
		t.Fatalf("repeat: %v steps=%d %+v", err, len(p.Steps), res)
	}
	if _, err := os.Stat(filepath.Join(e.j.Dir, "op2")); err == nil {
		t.Fatal("a converged repeat must leave no journal entry")
	}
}

func TestTunnelSwitchTwoAndThreeTunnels(t *testing.T) {
	e := setup(t, ownerCfg)
	own := map[string]bool{"domain-list7": true}
	if _, _, err := run(t, e, "a", plan.Desired{Groups: []plan.Group{youtube}, OwnedGroups: own}); err != nil {
		t.Fatal(err)
	}
	for i, tun := range []string{"Wireguard1", "OpkgTun2", "OpkgTun4"} {
		g := youtube
		g.Target = tun
		res, _, err := run(t, e, "s"+string(rune('0'+i)), plan.Desired{Groups: []plan.Group{g}, OwnedGroups: own})
		if err != nil || res.Outcome.State != "done" {
			t.Fatalf("%s: %v %+v", tun, err, res)
		}
		rs := e.full(t).RoutesOf("domain-list7")
		if len(rs) != 1 || rs[0].Target != tun {
			t.Fatalf("%s: routes %+v", tun, rs)
		}
		// The owner's lists stay on their tunnel.
		if r := e.full(t).RoutesOf("domain-list0"); len(r) != 1 || r[0].Target != "OpkgTun4" {
			t.Fatalf("foreign list moved: %+v", r)
		}
	}
	protectedIntact(t, e)
}

func TestForeignGroupNeverWritten(t *testing.T) {
	e := setup(t, ownerCfg)
	// A desired change of the owner's own list (not proven VWARD's) is refused, nothing sent.
	g := plan.Group{Name: "domain-list0", Include: []string{"t.me"}, Target: "Wireguard1", Options: "auto"}
	_, p, err := run(t, e, "f", plan.Desired{Groups: []plan.Group{g}, OwnedGroups: map[string]bool{}})
	if err != nil || len(p.Steps) != 0 || len(p.Refused) != 1 || !strings.Contains(p.Refused[0], "foreign") {
		t.Fatalf("%v %+v", err, p)
	}
	// One domain, one assignment: t.me already goes through the owner's list to OpkgTun4.
	g2 := plan.Group{Name: "domain-list9", Include: []string{"t.me", "new.example"}, Target: "Wireguard1", Options: "auto"}
	_, p, _ = run(t, e, "f2", plan.Desired{Groups: []plan.Group{g2}, OwnedGroups: map[string]bool{"domain-list9": true}})
	if len(p.Refused) != 1 || !strings.Contains(p.Refused[0], "foreign-coverage") {
		t.Fatalf("refused %v", p.Refused)
	}
	for _, s := range p.Steps {
		if strings.Contains(s.Cmd, "t.me") {
			t.Fatalf("t.me planned twice: %v", s.Cmd)
		}
	}
	// Only the second request sent anything: its batch and the save.
	if len(e.fake.batches) != 2 {
		t.Fatalf("batches %v", e.fake.batches)
	}
	protectedIntact(t, e)
}

func TestProtectedRefused(t *testing.T) {
	m := ndm.ParseRunning(ownerCfg)
	p := &plan.Plan{Steps: []plan.Step{{Area: "x", Cmd: "no ip route 8.8.8.0 255.255.255.0 OpkgTun4 auto", Undo: "ip route 8.8.8.0 255.255.255.0 OpkgTun4 auto"}}}
	for _, s := range p.Steps {
		if bad, _ := plan.DefaultProtected(s.Cmd); !bad {
			t.Fatal("ip route must be protected")
		}
	}
	for _, c := range []string{"no ip name-server 8.8.8.8 youtube.com on OpkgTun4", "dns-proxy no https upstream https://dns.nextdns.io/abc dnsm on ISP domain nextdns.example"} {
		if bad, _ := plan.DefaultProtected(c); !bad {
			t.Fatalf("%s must be protected", c)
		}
	}
	// A desired image that would remove the NextDNS row (not owned) plans nothing for it.
	pl, err := plan.Build(m, plan.Desired{DoH: []plan.DoHRow{}, OwnedDoH: map[string]bool{}}, nil)
	if err != nil || len(pl.Steps) != 0 {
		t.Fatalf("%v %+v", err, pl)
	}
}

func TestMidBatchFailureCompensated(t *testing.T) {
	e := setup(t, ownerCfg)
	pre := e.fake.running()
	e.fake.refuseOn = "ytimg.com" // Keenetic refuses one command in the middle
	res, _, err := run(t, e, "mid", plan.Desired{Groups: []plan.Group{youtube}, OwnedGroups: map[string]bool{"domain-list7": true}})
	if err != nil {
		t.Fatal(err)
	}
	if res.Outcome.State != "failed" || !strings.Contains(res.Outcome.Reason, "compensated") {
		t.Fatalf("outcome %+v", res.Outcome)
	}
	if got := e.fake.running(); got != pre {
		t.Fatalf("router not back to its pre-image:\n%s\n---\n%s", got, pre)
	}
	if e.j.State("mid") != "failed" {
		t.Fatalf("journal %s", e.j.State("mid"))
	}
	protectedIntact(t, e)
}

func TestLostReply(t *testing.T) {
	// Reply lost after everything was applied: the read after proves it, done.
	e := setup(t, ownerCfg)
	m := e.model(t)
	p, _ := plan.Build(m, plan.Desired{Groups: []plan.Group{youtube}, OwnedGroups: map[string]bool{"domain-list7": true}}, nil)
	e.fake.dropAt = len(p.Steps) // after the last command
	res, err := Run(e.r, e.j, "lost1", m, p)
	if err != nil || res.Outcome.State != "done" {
		t.Fatalf("%v %+v", err, res)
	}
	// Reply lost before anything was applied: proven not applied, failed (never replayed).
	e2 := setup(t, ownerCfg)
	m2 := e2.model(t)
	p2, _ := plan.Build(m2, plan.Desired{Groups: []plan.Group{youtube}, OwnedGroups: map[string]bool{"domain-list7": true}}, nil)
	e2.fake.dropAt = 0
	res, err = Run(e2.r, e2.j, "lost0", m2, p2)
	if err != nil || res.Outcome.State != "failed" {
		t.Fatalf("%v %+v", err, res)
	}
	if _, err := Run(e2.r, e2.j, "lost0", m2, p2); !errors.Is(err, journal.ErrReused) {
		t.Fatalf("operation id must never be replayed: %v", err)
	}
}

func TestChangedSincePlanRefused(t *testing.T) {
	e := setup(t, ownerCfg)
	m := e.model(t)
	p, _ := plan.Build(m, plan.Desired{Groups: []plan.Group{youtube}, OwnedGroups: map[string]bool{"domain-list7": true}}, nil)
	e.fake.apply("object-group fqdn domain-list7 include other.example") // someone else, meanwhile
	_, err := Run(e.r, e.j, "race", m, p)
	if !errors.Is(err, ErrChanged) {
		t.Fatalf("want ErrChanged, got %v", err)
	}
	if len(e.fake.batches) != 0 || e.j.State("race") != "absent" {
		t.Fatalf("nothing may be sent or journaled: %v %s", e.fake.batches, e.j.State("race"))
	}
}

func TestUnknownBlocks(t *testing.T) {
	e := setup(t, ownerCfg)
	os.MkdirAll(filepath.Join(e.j.Dir, "old"), 0o700)
	os.WriteFile(filepath.Join(e.j.Dir, "old", "pending"), []byte("{}"), 0o600)
	_, _, err := run(t, e, "next", plan.Desired{Groups: []plan.Group{youtube}, OwnedGroups: map[string]bool{"domain-list7": true}})
	if !errors.Is(err, journal.ErrBlocked) || len(e.fake.batches) != 0 {
		t.Fatalf("a pending operation must block: %v", err)
	}
}

func TestDoHLimit(t *testing.T) {
	cfg := ownerCfg
	var rows []string
	for i := 0; i < 6; i++ {
		rows = append(rows, "    https upstream https://dns.example/"+string(rune('a'+i))+" dnsm on ISP domain d"+string(rune('a'+i))+".example")
	}
	cfg = strings.Replace(cfg, "    https upstream https://dns.nextdns.io", strings.Join(rows, "\n")+"\n    https upstream https://dns.nextdns.io", 1)
	e := setup(t, cfg) // 7 rows taken by others
	want := plan.Desired{DoH: []plan.DoHRow{{URL: "https://smart.example/x", Iface: "ISP", Domain: "chatgpt.com"}, {URL: "https://smart.example/x", Iface: "ISP", Domain: "openai.com"}}, OwnedDoH: map[string]bool{}}
	res, p, err := run(t, e, "doh", want)
	if err != nil || res.Outcome.State != "done" {
		t.Fatalf("%v %+v", err, res)
	}
	if len(p.Steps) != 1 || len(p.Refused) != 1 || !strings.Contains(p.Refused[0], "dns-limit") {
		t.Fatalf("steps %v refused %v", p.Steps, p.Refused)
	}
	if n := len(e.full(t).DoH); n != 8 {
		t.Fatalf("rows %d", n)
	}
	protectedIntact(t, e)
}
