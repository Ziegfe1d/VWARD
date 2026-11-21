package adaptive

import (
	"context"
	"strings"
	"sync"
	"testing"
	"time"
)

// certScript returns the actual verdict and certificate marker, unlike scripted
// (which only varies Verdict). It lets these tests exercise the production
// wrong-cert path without making network requests.
type certScript struct {
	mu      sync.Mutex
	results map[string]ProbeResult
	calls   []string
}

func (p *certScript) Probe(_ context.Context, host, dev string) ProbeResult {
	p.mu.Lock()
	defer p.mu.Unlock()
	key := dev + " " + host
	p.calls = append(p.calls, key)
	if r, ok := p.results[key]; ok {
		return r
	}
	return ProbeResult{Unknown, "not scripted"}
}

func (p *certScript) count(key string) int {
	p.mu.Lock()
	defer p.mu.Unlock()
	n := 0
	for _, call := range p.calls {
		if call == key {
			n++
		}
	}
	return n
}

func TestReconcileWrongCertNeedsVerifiedDirectAnswer(t *testing.T) {
	const host = "cert.example.com"
	cases := []struct {
		name      string
		tunnel    string
		direct    ProbeResult
		vpn       ProbeResult
		wantEvent string
		wantCount int
		vpnCalls  int
	}{
		{"both paths wrong certificate", "opkgtun4", ProbeResult{Open, "http 200 wrong-cert"}, ProbeResult{Open, "http 200 wrong-cert"}, "DIRECT_UNKNOWN", 0, 1},
		{"vpn is unavailable", "opkgtun4", ProbeResult{Open, "http 200 wrong-cert"}, ProbeResult{Blocked, "tls: timeout"}, "DIRECT_UNKNOWN", 0, 1},
		{"no tunnel configured", "", ProbeResult{Open, "http 200 wrong-cert"}, ProbeResult{}, "DIRECT_UNKNOWN", 0, 0},
		{"vpn has a valid answer", "opkgtun4", ProbeResult{Open, "http 200 wrong-cert"}, ProbeResult{Open, "http 200"}, "DIRECT_FAIL", 0, 1},
		{"403 refusal remains blocked", "opkgtun4", ProbeResult{Open, "http 403"}, ProbeResult{Open, "http 200"}, "DIRECT_FAIL", 0, 1},
		{"verified direct answer can remove", "opkgtun4", ProbeResult{Open, "http 200"}, ProbeResult{}, "REMOVE", 3, 0},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			p := &certScript{results: map[string]ProbeResult{"ppp0 " + host: tc.direct}}
			if tc.tunnel != "" {
				p.results[tc.tunnel+" "+host] = tc.vpn
			}
			now := time.Unix(1000, 0)
			o := &Owned{Names: map[string]*Name{
				host: {Streak: 2, LastOK: now.Add(-10 * time.Minute),
					VPNFail: 2, LastVPNFail: now.Add(-10 * time.Minute)},
			}}
			rc := ReconcileConfig{Every: time.Minute, Batch: 8, Threshold: 3,
				MinGap: 4 * time.Minute, TunnelDev: tc.tunnel}
			removed, events := Reconcile(context.Background(), o, p, "ppp0", rc, now)
			if len(events) != 1 || events[0].Event != tc.wantEvent {
				t.Fatalf("events = %+v, want %s", events, tc.wantEvent)
			}
			if got := o.Names[host].Streak; got != tc.wantCount {
				t.Fatalf("direct success streak = %d, want %d", got, tc.wantCount)
			}
			if n := o.Names[host]; n.VPNFail != 0 || !n.LastVPNFail.IsZero() {
				t.Fatalf("unverified evidence preserved a failure streak: %+v", n)
			}
			if (len(removed) == 1) != (tc.wantEvent == "REMOVE") {
				t.Fatalf("removed = %v, event = %s", removed, tc.wantEvent)
			}
			if tc.wantEvent == "DIRECT_UNKNOWN" && !o.Names[host].LastOK.IsZero() {
				t.Fatalf("ambiguous result kept last valid confirmation: %+v", o.Names[host])
			}
			if got := p.count("opkgtun4 " + host); got != tc.vpnCalls {
				t.Fatalf("vpn calls = %d, want %d; calls = %v", got, tc.vpnCalls, p.calls)
			}
		})
	}
}

func TestEngineWrongCertDoesNotReportDirectOK(t *testing.T) {
	const host = "cert.example.com"
	cases := []struct {
		name     string
		tunnel   string
		hinted   bool
		direct   ProbeResult
		vpn      ProbeResult
		want     Outcome
		vpnCalls int
	}{
		{"ordinary both wrong", "opkgtun4", false, ProbeResult{Open, "http 200 wrong-cert"}, ProbeResult{Open, "http 200 wrong-cert"}, ProbeUnknown, 1},
		{"ordinary vpn offline", "opkgtun4", false, ProbeResult{Open, "http 200 wrong-cert"}, ProbeResult{Blocked, "tls: timeout"}, ProbeUnknown, 1},
		{"ordinary no tunnel", "", false, ProbeResult{Open, "http 200 wrong-cert"}, ProbeResult{}, ProbeUnknown, 0},
		{"ordinary vpn valid", "opkgtun4", false, ProbeResult{Open, "http 200 wrong-cert"}, ProbeResult{Open, "http 200"}, Add, 1},
		{"hinted both wrong", "opkgtun4", true, ProbeResult{Open, "http 200 wrong-cert"}, ProbeResult{Open, "http 200 wrong-cert"}, ProbeUnknown, 1},
		{"hinted vpn valid", "opkgtun4", true, ProbeResult{Open, "http 200 wrong-cert"}, ProbeResult{Open, "http 200"}, Add, 1},
		{"regular direct answer", "opkgtun4", false, ProbeResult{Open, "http 200"}, ProbeResult{}, DirectOK, 0},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			p := &certScript{results: map[string]ProbeResult{"ppp0 " + host: tc.direct}}
			if tc.tunnel != "" {
				p.results[tc.tunnel+" "+host] = tc.vpn
			}
			c := DefaultConfig()
			c.WanDev, c.TunnelDev, c.Retry = "ppp0", tc.tunnel, time.Millisecond
			e := New(c, p)
			if tc.hinted {
				e.SetHints(map[string]bool{host: true})
			}
			r := e.Check(context.Background(), host)
			if r.Outcome != tc.want {
				t.Fatalf("outcome = %s (%s), want %s; calls = %v", r.Outcome, r.Why, tc.want, p.calls)
			}
			if tc.want == ProbeUnknown && !strings.Contains(r.Why, "wrong-cert") {
				t.Fatalf("ambiguous certificate not explained: %+v", r)
			}
			if got := p.count("opkgtun4 " + host); got != tc.vpnCalls {
				t.Fatalf("vpn calls = %d, want %d; calls = %v", got, tc.vpnCalls, p.calls)
			}
		})
	}
}
