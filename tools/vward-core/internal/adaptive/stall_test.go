package adaptive

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// The «16 KB» block (TSPU since 06.2025): the answer freezes after its first kilobytes.
func TestProbeStall(t *testing.T) {
	needRoot(t)
	for _, c := range []struct {
		send   int
		freeze bool
		want   string
	}{
		{20 << 10, true, "http 200 stall"}, // froze after 20 KB: the block
		{2 << 10, true, "http 200"},        // a short page that keeps the connection: no proof
		{60 << 10, true, "http 200"},       // past 40 KB: no 16 KB block
		{20 << 10, false, "http 200"},      // a 20 KB page that ends
	} {
		c := c
		hold := make(chan struct{})
		srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(200)
			w.Write([]byte(strings.Repeat("x", c.send)))
			w.(http.Flusher).Flush()
			if c.freeze {
				select {
				case <-hold:
				case <-r.Context().Done():
				}
			}
		}))
		_, port, _ := net.SplitHostPort(srv.Listener.Addr().String())
		p := NewProber(time.Second, "")
		p.Port = port
		p.Lookup = func(context.Context, string) ([]net.IP, error) { return []net.IP{net.ParseIP("127.0.0.1")}, nil }
		r := p.Probe(context.Background(), "example.com", "lo")
		close(hold)
		srv.Close()
		if r.Verdict != Open || r.Why != c.want {
			t.Fatalf("sent %d freeze %v: %+v, want %q", c.send, c.freeze, r, c.want)
		}
	}
}

// A freeze directly and the whole answer through the VPN: into the group; frozen both ways: not.
func TestRefusedHereStall(t *testing.T) {
	o := func(why string) ProbeResult { return ProbeResult{Open, why} }
	for _, c := range []struct {
		d, v ProbeResult
		want bool
	}{
		{o("http 200 stall"), o("http 200"), true},
		{o("http 200 wrong-cert stall"), o("http 200"), true},
		{o("http 200 stall"), o("http 200 stall"), false}, // a slow site
		{o("http 200 stall"), ProbeResult{Blocked, "connect: timeout"}, false},
		{o("http 403"), o("http 200 stall"), false},
		{o("http 200"), o("http 200"), false},
	} {
		if RefusedHere(c.d, c.v) != c.want {
			t.Fatalf("RefusedHere(%v, %v) != %v", c.d, c.v, c.want)
		}
	}
	if !Suspect(o("http 200 stall")) || Suspect(o("http 200")) || !WrongCert(o("http 200 wrong-cert stall")) || Stalled(o("tls: stall")) {
		t.Fatal("the marks of the Why")
	}
}

func TestCheckStall(t *testing.T) {
	o := func(why string) ProbeResult { return ProbeResult{Open, why} }
	p := &coded{ans: map[string][]ProbeResult{"ppp0 cdn-site.com": {o("http 200 stall")}, "opkgtun4 cdn-site.com": {o("http 200")}}}
	cfg := DefaultConfig()
	cfg.WanDev, cfg.TunnelDev = "ppp0", "opkgtun4"
	r := New(cfg, p).Check(context.Background(), "cdn-site.com")
	if r.Outcome != Add || r.Direct != "http 200 stall refused" {
		t.Fatalf("frozen directly, whole through the VPN: %+v", r)
	}
	own := &Owned{Names: map[string]*Name{"cdn-site.com": {Streak: 2, LastOK: time.Unix(1, 0)}}}
	p = &coded{ans: map[string][]ProbeResult{"ppp0 cdn-site.com": {o("http 200 stall")}, "opkgtun4 cdn-site.com": {o("http 200")}}}
	rc := DefaultReconcile()
	rc.TunnelDev = "opkgtun4"
	if rm, ev := Reconcile(context.Background(), own, p, "ppp0", rc, time.Unix(600, 0)); len(rm) != 0 || len(ev) != 1 || ev[0].Event != "DIRECT_FAIL" {
		t.Fatalf("maintenance keeps a frozen name: %v %+v", rm, ev)
	}
}

// The wait for a silent path follows the measured connect time of the device.
func TestQuickWait(t *testing.T) {
	p := NewProber(3*time.Second, "")
	if q := p.quick("ppp0"); q != 3*time.Second {
		t.Fatalf("before a measurement: the whole limit, got %v", q)
	}
	p.measured("ppp0", 20*time.Millisecond)
	if q := p.quick("ppp0"); q != quickFloor {
		t.Fatalf("a fast link: the floor 1.5 s, got %v", q)
	}
	for i := 0; i < 40; i++ {
		p.measured("ppp0", 400*time.Millisecond)
	}
	if q := p.quick("ppp0"); q < 2300*time.Millisecond || q > 2400*time.Millisecond {
		t.Fatalf("a slow link: six times its time, got %v", q)
	}
	for i := 0; i < 40; i++ {
		p.measured("ppp0", 2*time.Second)
	}
	if q := p.quick("ppp0"); q != 3*time.Second {
		t.Fatalf("never above the limit, got %v", q)
	}
	if q := p.quick("opkgtun4"); q != 3*time.Second {
		t.Fatalf("each device its own, got %v", q)
	}
}
