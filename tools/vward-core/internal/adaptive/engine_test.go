package adaptive

import (
	"context"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/ndm"
)

// scripted: answers per device and host, in order (the last answer repeats); records calls.
type scripted struct {
	mu    sync.Mutex
	ans   map[string][]Verdict // "dev host" -> answers
	calls []string
}

func (s *scripted) Probe(_ context.Context, host, dev string) ProbeResult {
	s.mu.Lock()
	defer s.mu.Unlock()
	k := dev + " " + host
	s.calls = append(s.calls, k)
	a := s.ans[k]
	if len(a) == 0 {
		return ProbeResult{Unknown, "no script"}
	}
	v := a[0]
	if len(a) > 1 {
		s.ans[k] = a[1:]
	}
	return ProbeResult{v, v.String()}
}

func (s *scripted) count(prefix string) int {
	n := 0
	for _, c := range s.calls {
		if strings.HasPrefix(c, prefix) {
			n++
		}
	}
	return n
}

const cfgText = `object-group fqdn AdaptiveAuto
 include known.example.net
!
object-group fqdn Youtube
 include youtube.com
!
dns-proxy
 route object-group AdaptiveAuto OpkgTun4 auto
 route object-group Youtube OpkgTun4 auto
 https upstream https://smart.example/dns dnsm on ISP domain chatgpt.com
!
`

func engine(ans map[string][]Verdict) (*Engine, *scripted) {
	p := &scripted{ans: ans}
	c := DefaultConfig()
	c.WanDev, c.TunnelDev, c.Retry = "ppp0", "opkgtun4", time.Millisecond
	c.Skip = []string{"never.example.org"}
	e := New(c, p)
	e.SetConfig(ndm.ParseRunning(cfgText))
	return e, p
}

const O, B, U = Open, Blocked, Unknown

func TestDecisions(t *testing.T) {
	ctl := map[string][]Verdict{"ppp0 ya.ru": {O}}
	for _, c := range []struct {
		name string
		host string
		ans  map[string][]Verdict
		want Outcome
	}{
		{"opens directly", "site.example.com", map[string][]Verdict{"ppp0 site.example.com": {O}}, DirectOK},
		{"second direct check opens", "site.example.com", map[string][]Verdict{"ppp0 site.example.com": {B, O}, "opkgtun4 site.example.com": {O}}, DirectOK},
		{"blocked, vpn twice", "site.example.com", merge(ctl, map[string][]Verdict{"ppp0 site.example.com": {B, B}, "opkgtun4 site.example.com": {O, O}}), Add},
		{"blocked, control sites fail", "site.example.com", map[string][]Verdict{"ppp0 site.example.com": {B, B}, "opkgtun4 site.example.com": {O, O}, "ppp0 ya.ru": {B}, "ppp0 vk.com": {B}}, ISPUnreliable},
		{"blocked, control unknown", "site.example.com", map[string][]Verdict{"ppp0 site.example.com": {B, B}, "opkgtun4 site.example.com": {O, O}, "ppp0 ya.ru": {U}, "ppp0 vk.com": {B}}, ProbeUnknown},
		{"blocked, vpn fails", "site.example.com", merge(ctl, map[string][]Verdict{"ppp0 site.example.com": {B, B}, "opkgtun4 site.example.com": {B}}), TunnelFail},
		{"blocked, vpn once", "site.example.com", merge(ctl, map[string][]Verdict{"ppp0 site.example.com": {B, B}, "opkgtun4 site.example.com": {O, B}}), TunnelUnstable},
		{"direct unknown", "site.example.com", map[string][]Verdict{"ppp0 site.example.com": {U}}, ProbeUnknown},
		{"direct retry unknown", "site.example.com", map[string][]Verdict{"ppp0 site.example.com": {B, U}, "opkgtun4 site.example.com": {O, O}}, ProbeUnknown},
		{"vpn unknown", "site.example.com", merge(ctl, map[string][]Verdict{"ppp0 site.example.com": {B, B}, "opkgtun4 site.example.com": {U}}), ProbeUnknown},
		{"vpn retry unknown", "site.example.com", merge(ctl, map[string][]Verdict{"ppp0 site.example.com": {B, B}, "opkgtun4 site.example.com": {O, U}}), ProbeUnknown},
		{"ru zone", "shop.example.ru", nil, Skip},
		{"рф zone", "xn--80ak6aa92e.xn--p1ai", nil, Skip},
		{"yandex", "mc.yandex.net", nil, Skip},
		{"in the group", "cdn.known.example.net", nil, Known},
		{"owner's list", "m.youtube.com", nil, Skip},
		{"Smart DNS", "chatgpt.com", nil, Skip},
		{"skip list", "a.never.example.org", nil, Skip},
		{"local name", "printer.lan", nil, Skip},
		{"reverse", "1.0.168.192.in-addr.arpa", nil, Skip},
		{"service name", "_dmarc.example.com", nil, Skip},
	} {
		t.Run(c.name, func(t *testing.T) {
			e, p := engine(c.ans)
			r := e.Check(context.Background(), c.host)
			if r.Outcome != c.want {
				t.Fatalf("%s: %s (%s), want %s; calls %v", c.host, r.Outcome, r.Why, c.want, p.calls)
			}
			if c.ans == nil && len(p.calls) != 0 {
				t.Fatalf("no check expected, got %v", p.calls)
			}
		})
	}
}

func merge(a, b map[string][]Verdict) map[string][]Verdict {
	m := map[string][]Verdict{}
	for k, v := range a {
		m[k] = append([]Verdict(nil), v...)
	}
	for k, v := range b {
		m[k] = append([]Verdict(nil), v...)
	}
	return m
}

// A site that opens directly is never checked through the VPN.
func TestNoVPNCheckForDirect(t *testing.T) {
	e, p := engine(map[string][]Verdict{"ppp0 site.example.com": {O}})
	e.Check(context.Background(), "site.example.com")
	if p.count("opkgtun4 ") != 0 {
		t.Fatalf("vpn checked: %v", p.calls)
	}
}

// Results hold: a second query within the time does not check again; an expired one does.
func TestCache(t *testing.T) {
	e, p := engine(map[string][]Verdict{"ppp0 site.example.com": {O}})
	now := time.Unix(1000, 0)
	e.Now = func() time.Time { return now }
	e.Check(context.Background(), "site.example.com")
	if r := e.Check(context.Background(), "Site.Example.com."); r.Outcome != Cached || len(p.calls) != 1 {
		t.Fatalf("cached: %+v %v", r, p.calls)
	}
	now = now.Add(7 * time.Hour)
	e.Prune()
	e.Check(context.Background(), "site.example.com")
	if len(p.calls) != 2 {
		t.Fatalf("expired result not checked again: %v", p.calls)
	}
}

// The control sites are asked once for many failing sites within ControlFor.
func TestControlCached(t *testing.T) {
	ans := map[string][]Verdict{"ppp0 ya.ru": {O}}
	for _, h := range []string{"a.example.com", "b.example.com", "c.example.com"} {
		ans["ppp0 "+h] = []Verdict{B, B}
		ans["opkgtun4 "+h] = []Verdict{O, O}
	}
	e, p := engine(ans)
	for _, h := range []string{"a.example.com", "b.example.com", "c.example.com"} {
		if r := e.Check(context.Background(), h); r.Outcome != Add {
			t.Fatalf("%s: %+v", h, r)
		}
	}
	if p.count("ppp0 ya.ru") != 1 {
		t.Fatalf("control asked %d times", p.count("ppp0 ya.ru"))
	}
}

// The VPN checks run alongside the second direct check: a blocked site is decided in about
// the time of two checks, not four.
func TestParallel(t *testing.T) {
	slow := &slowProber{d: 80 * time.Millisecond, ans: map[string]Verdict{"ppp0 s.example.com": B, "opkgtun4 s.example.com": O, "ppp0 ya.ru": O}}
	c := DefaultConfig()
	c.WanDev, c.TunnelDev, c.Retry = "ppp0", "opkgtun4", 10*time.Millisecond
	e := New(c, slow)
	t0 := time.Now()
	if r := e.Check(context.Background(), "s.example.com"); r.Outcome != Add {
		t.Fatalf("%+v", r)
	}
	// Sequential: direct, direct, control, vpn, vpn = 5 checks. In parallel: about 3.
	if d := time.Since(t0); d > 4*80*time.Millisecond {
		t.Fatalf("took %v: the checks did not overlap", d)
	}
}

type slowProber struct {
	d   time.Duration
	ans map[string]Verdict
}

func (s *slowProber) Probe(ctx context.Context, host, dev string) ProbeResult {
	time.Sleep(s.d)
	return ProbeResult{s.ans[dev+" "+host], "slow"}
}

// Owner 12.11.2026 (remote access to the router did not always connect): KeenDNS and Keenetic's
// cloud never go into AdaptiveAuto, under either brand.
func TestRouterOwnNamesStayOnTheProvider(t *testing.T) {
	for _, h := range []string{"silentlink.netcraze.pro", "my.keenetic.pro", "x.keenetic.link", "netcraze.pro", "ndss.keenetic.io"} {
		if !routerOwn(h) {
			t.Fatalf("%s must stay on the provider", h)
		}
	}
	for _, h := range []string{"notkeenetic.pro", "netcraze.pro.example.com", "chatgpt.com"} {
		if routerOwn(h) {
			t.Fatalf("%s is not the router's own", h)
		}
	}
	e := New(Config{}, nil)
	if r := e.Check(context.Background(), "silentlink.netcraze.pro"); r.Outcome != Skip {
		t.Fatalf("KeenDNS name checked: %+v", r)
	}
}
