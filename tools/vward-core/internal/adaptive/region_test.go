package adaptive

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// The answers the owner's router got directly (16.11.2026) and the usual ones.
func TestRegionRefusal(t *testing.T) {
	for body, want := range map[string]bool{
		`{"error":{"code":"unsupported_country_region_territory","message":"Country, region, or territory not supported","param":null,"type":"request_forbidden"}}`: true,
		`<p>Error code: 1009</p><p>The owner of this website has banned the country or region your IP address is in</p>`:                                            true,
		`This service is not available in your country.`:                                  true,
		`{ "error": { "type": "forbidden", "message": "Request not allowed" }}`:           false,
		`<html><head><title>403 Forbidden</title></head><body>nginx</body></html>`:        false,
		`<!DOCTYPE html><html class="no-js" lang="en-US"><title>Just a moment...</title>`: false,
	} {
		if RegionRefusal(body) != want {
			t.Fatalf("RegionRefusal(%.60q) = %v", body, !want)
		}
	}
}

// A direct 403 and another answer through the VPN: refused here (api.anthropic.com).
func TestRefusedHere(t *testing.T) {
	o := func(why string) ProbeResult { return ProbeResult{Open, why} }
	for _, c := range []struct {
		d, v ProbeResult
		want bool
	}{
		{o("http 403"), o("http 404"), true},
		{o("http 403"), o("http 200"), true},
		{o("http 403"), o("http 403"), false},                        // the site refuses the root path anywhere
		{o("http 403"), ProbeResult{Blocked, "tls: timeout"}, false}, // the VPN does not open it either
		{o("http 403"), ProbeResult{Unknown, "no device"}, false},
		{o("http 200"), o("http 404"), false},
	} {
		if RefusedHere(c.d, c.v) != c.want {
			t.Fatalf("RefusedHere(%v, %v) != %v", c.d, c.v, c.want)
		}
	}
}

// coded: answers per device and host with their Why, in order (the last repeats).
type coded struct{ ans map[string][]ProbeResult }

func (c *coded) Probe(_ context.Context, host, dev string) ProbeResult {
	a := c.ans[dev+" "+host]
	if len(a) == 0 {
		return ProbeResult{Unknown, "no script"}
	}
	r := a[0]
	if len(a) > 1 {
		c.ans[dev+" "+host] = a[1:]
	}
	return r
}

func TestCheckDirect403(t *testing.T) {
	o := func(why string) ProbeResult { return ProbeResult{Open, why} }
	for _, c := range []struct {
		vpn  ProbeResult
		want Outcome
	}{
		{o("http 404"), Add},      // api.anthropic.com: refused directly, answers through the VPN
		{o("http 403"), DirectOK}, // 403 both ways: nothing proven
		{ProbeResult{Blocked, "connect: timeout"}, DirectOK},
	} {
		p := &coded{ans: map[string][]ProbeResult{"ppp0 api.example.com": {o("http 403")}, "opkgtun4 api.example.com": {c.vpn}}}
		cfg := DefaultConfig()
		cfg.WanDev, cfg.TunnelDev = "ppp0", "opkgtun4"
		r := New(cfg, p).Check(context.Background(), "api.example.com")
		if r.Outcome != c.want {
			t.Fatalf("vpn %v: %+v, want %s", c.vpn, r, c.want)
		}
		if c.want == Add && r.Direct != "http 403 refused" {
			t.Fatalf("the reason kept: %+v", r)
		}
	}
}

// Maintenance: a name whose direct answer is a 403 the VPN does not give stays in the group.
func TestReconcileDirect403(t *testing.T) {
	o := func(why string) ProbeResult { return ProbeResult{Open, why} }
	rc := ReconcileConfig{Every: time.Minute, Batch: 8, Threshold: 3, MinGap: time.Minute, TunnelDev: "opkgtun4"}
	own := &Owned{Names: map[string]*Name{"api.example.com": {Streak: 2, LastOK: time.Unix(1, 0)}}}
	p := &coded{ans: map[string][]ProbeResult{"ppp0 api.example.com": {o("http 403")}, "opkgtun4 api.example.com": {o("http 404")}}}
	rm, ev := Reconcile(context.Background(), own, p, "ppp0", rc, time.Unix(600, 0))
	if len(rm) != 0 || len(ev) != 1 || ev[0].Event != "DIRECT_FAIL" || own.Names["api.example.com"].Streak != 0 {
		t.Fatalf("refused directly: stays, streak starts over: %v %+v %+v", rm, ev, own.Names["api.example.com"])
	}
	own = &Owned{Names: map[string]*Name{"x.example.com": {}}}
	p = &coded{ans: map[string][]ProbeResult{"ppp0 x.example.com": {o("http 403")}, "opkgtun4 x.example.com": {o("http 403")}}}
	if _, ev := Reconcile(context.Background(), own, p, "ppp0", rc, time.Unix(600, 0)); len(ev) != 1 || ev[0].Event != "DIRECT_CONFIRM" {
		t.Fatalf("403 both ways: opens directly as before: %+v", ev)
	}
}

// The probe reads the body of a 403 (GET) and finds the refusal of the country.
func TestProbe403Body(t *testing.T) {
	needRoot(t)
	for body, want := range map[string]string{
		`{"error":{"code":"unsupported_country_region_territory"}}`: "http 403 region",
		`{"type":"forbidden","message":"Request not allowed"}`:      "http 403",
	} {
		b := body
		srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.Method != http.MethodGet {
				w.WriteHeader(405)
				return
			}
			w.WriteHeader(403)
			w.Write([]byte(b))
		}))
		_, port, _ := net.SplitHostPort(srv.Listener.Addr().String())
		p := NewProber(2*time.Second, "")
		p.Port = port
		p.Lookup = func(context.Context, string) ([]net.IP, error) { return []net.IP{net.ParseIP("127.0.0.1")}, nil }
		// example.com: the name of httptest's certificate (no «wrong-cert» here).
		r := p.Probe(context.Background(), "example.com", "lo")
		srv.Close()
		if r.Why != want {
			t.Fatalf("403 %q: %+v, want %q", body, r, want)
		}
	}
}

// A direct 403 while the tunnel does not answer is no «opens directly» (owner's journal 16.11.2026:
// MAINT_DIRECT_CONFIRM chatgpt.com streak=1/3 http 403 half a minute before the tunnel was restarted;
// three such rounds took ChatGPT out of the VPN). The name stays and its streak does not grow.
func TestReconcileDirect403TunnelSilent(t *testing.T) {
	o := func(why string) ProbeResult { return ProbeResult{Open, why} }
	rc := ReconcileConfig{Every: time.Minute, Batch: 8, Threshold: 3, MinGap: time.Minute, TunnelDev: "opkgtun0"}
	own := &Owned{Names: map[string]*Name{"chatgpt.com": {Streak: 2, LastOK: time.Unix(1, 0)}}}
	p := &coded{ans: map[string][]ProbeResult{"ppp0 chatgpt.com": {o("http 403")}, "opkgtun0 chatgpt.com": {{Blocked, "connect: timeout"}}}}
	rm, ev := Reconcile(context.Background(), own, p, "ppp0", rc, time.Unix(600, 0))
	if len(rm) != 0 || len(ev) != 1 || ev[0].Event != "DIRECT_UNKNOWN" || own.Names["chatgpt.com"].Streak != 2 {
		t.Fatalf("403 directly, tunnel silent: stays, streak kept, nothing counted: %v %+v %+v", rm, ev, own.Names["chatgpt.com"])
	}
}
