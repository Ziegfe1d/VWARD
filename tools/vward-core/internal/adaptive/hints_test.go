package adaptive

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

func TestHintsReload(t *testing.T) {
	p := filepath.Join(t.TempDir(), "hints.conf")
	h := &Hints{Path: p}
	if changed, err := h.Reload(); err != nil || changed || h.Len() != 0 {
		t.Fatalf("no file: empty, no error: %v %v %d", changed, err, h.Len())
	}
	os.WriteFile(p, []byte("# comment\nChatGPT.com\n*.openai.com\n.claude.ai\nnot a name\n\nx\n"), 0o644)
	if changed, err := h.Reload(); err != nil || !changed || h.Len() != 3 {
		t.Fatalf("read: %v %v %v", changed, err, h.Set())
	}
	for _, n := range []string{"chatgpt.com", "openai.com", "claude.ai"} {
		if !h.Set()[n] {
			t.Fatalf("%s missing: %v", n, h.Set())
		}
	}
	if changed, _ := h.Reload(); changed {
		t.Fatal("unchanged file: not read again")
	}
	// The sources' catalog: v2fly (a directory of every service's domains) is left out.
	cat := filepath.Join(t.TempDir(), "hints-catalog.tsv")
	os.WriteFile(cat, []byte("youtube.com|itdog|youtube\ngoogle.com|v2fly|google\nx.org|antifilter|antifilter-community\nbad|refilter|x\n"), 0o644)
	hc := &Hints{Path: cat}
	if _, err := hc.Reload(); err != nil || hc.Len() != 2 || !hc.Set()["youtube.com"] || !hc.Set()["x.org"] || hc.Set()["google.com"] {
		t.Fatalf("catalog: %v %v", err, hc.Set())
	}
	time.Sleep(10 * time.Millisecond)
	os.WriteFile(p, []byte("x.com\n"), 0o644)
	os.Chtimes(p, time.Now().Add(time.Minute), time.Now().Add(time.Minute))
	if changed, _ := h.Reload(); !changed || h.Len() != 1 {
		t.Fatalf("changed file: read again: %v", h.Set())
	}
	os.Remove(p)
	if changed, _ := h.Reload(); !changed || h.Len() != 0 {
		t.Fatal("file gone: empty set")
	}
}

// counted: answers per device and host, in order; counts the calls of each.
type counted struct {
	mu    sync.Mutex
	ans   map[string][]ProbeResult
	calls map[string]int
	delay map[string]time.Duration
}

func (c *counted) Probe(_ context.Context, host, dev string) ProbeResult {
	c.mu.Lock()
	k := dev + " " + host
	c.calls[k]++
	d := c.delay[k]
	a := c.ans[k]
	r := ProbeResult{Unknown, "no script"}
	if len(a) > 0 {
		r = a[0]
		if len(a) > 1 {
			c.ans[k] = a[1:]
		}
	}
	c.mu.Unlock()
	time.Sleep(d)
	return r
}

func hintedEngine(ans map[string][]ProbeResult, delay map[string]time.Duration) (*Engine, *counted) {
	p := &counted{ans: ans, calls: map[string]int{}, delay: delay}
	cfg := DefaultConfig()
	cfg.WanDev, cfg.TunnelDev, cfg.Retry = "ppp0", "opkgtun4", 300*time.Millisecond
	e := New(cfg, p)
	e.SetHints(map[string]bool{"blocked-site.com": true})
	return e, p
}

// A name of the source lists (a parent counts): one direct check and one VPN check at the same
// time - no retry a second later, no second VPN check.
func TestHintedFastPath(t *testing.T) {
	o, b := ProbeResult{Open, "http 200"}, ProbeResult{Blocked, "tls: timeout"}
	e, p := hintedEngine(map[string][]ProbeResult{
		"ppp0 www.blocked-site.com": {b}, "opkgtun4 www.blocked-site.com": {o}, "ppp0 ya.ru": {o}}, nil)
	t0 := time.Now()
	r := e.Check(context.Background(), "www.blocked-site.com")
	if r.Outcome != Add || p.calls["ppp0 www.blocked-site.com"] != 1 || p.calls["opkgtun4 www.blocked-site.com"] != 1 {
		t.Fatalf("hinted: %+v %v", r, p.calls)
	}
	if time.Since(t0) >= 300*time.Millisecond {
		t.Fatalf("no retry wait for a hinted name: %v", time.Since(t0))
	}
	// The same answers for a name that is not in the lists: the usual way (retry, VPN twice).
	e2, p2 := hintedEngine(map[string][]ProbeResult{
		"ppp0 other-site.com": {b, b}, "opkgtun4 other-site.com": {o, o}, "ppp0 ya.ru": {o}}, nil)
	if r := e2.Check(context.Background(), "other-site.com"); r.Outcome != Add || p2.calls["ppp0 other-site.com"] != 2 || p2.calls["opkgtun4 other-site.com"] != 2 {
		t.Fatalf("not hinted: %+v %v", r, p2.calls)
	}
}

// A hinted site that opens directly is decided at once: the VPN's answer is not waited for.
func TestHintedOpensDirectly(t *testing.T) {
	o := ProbeResult{Open, "http 200"}
	e, _ := hintedEngine(map[string][]ProbeResult{"ppp0 blocked-site.com": {o}, "opkgtun4 blocked-site.com": {o}},
		map[string]time.Duration{"opkgtun4 blocked-site.com": 2 * time.Second})
	t0 := time.Now()
	if r := e.Check(context.Background(), "blocked-site.com"); r.Outcome != DirectOK || time.Since(t0) > time.Second {
		t.Fatalf("opens directly: %+v in %v", r, time.Since(t0))
	}
}

func TestHintedOtherOutcomes(t *testing.T) {
	o, b, u := ProbeResult{Open, "http 200"}, ProbeResult{Blocked, "tls: timeout"}, ProbeResult{Unknown, "no address"}
	for _, c := range []struct {
		name string
		ans  map[string][]ProbeResult
		want Outcome
	}{
		{"provider down", map[string][]ProbeResult{"ppp0 blocked-site.com": {b}, "opkgtun4 blocked-site.com": {o}, "ppp0 ya.ru": {b}, "ppp0 vk.com": {b}}, ISPUnreliable},
		{"vpn fails too", map[string][]ProbeResult{"ppp0 blocked-site.com": {b}, "opkgtun4 blocked-site.com": {b}, "ppp0 ya.ru": {o}}, TunnelFail},
		{"direct unknown", map[string][]ProbeResult{"ppp0 blocked-site.com": {u}, "opkgtun4 blocked-site.com": {o}}, ProbeUnknown},
		{"403 directly, other through vpn", map[string][]ProbeResult{"ppp0 blocked-site.com": {{Open, "http 403"}}, "opkgtun4 blocked-site.com": {{Open, "http 404"}}}, Add},
	} {
		e, _ := hintedEngine(c.ans, nil)
		if r := e.Check(context.Background(), "blocked-site.com"); r.Outcome != c.want {
			t.Fatalf("%s: %+v, want %s", c.name, r, c.want)
		}
	}
}

// A certificate for another name directly and the right one through the VPN: a stub - refused.
func TestRefusedHereWrongCert(t *testing.T) {
	o := func(why string) ProbeResult { return ProbeResult{Open, why} }
	for _, c := range []struct {
		d, v ProbeResult
		want bool
	}{
		{o("http 200 wrong-cert"), o("http 200"), true},
		{o("http 302 wrong-cert"), o("http 301"), true},
		{o("http 200 wrong-cert"), o("http 200 wrong-cert"), false}, // the site's own certificate is wrong
		{o("http 403"), o("http 404 wrong-cert"), false},
		{o("http 200"), o("http 200"), false},
	} {
		if RefusedHere(c.d, c.v) != c.want || (Suspect(c.d) != (HTTPCode(c.d.Why) == "403" || WrongCert(c.d))) {
			t.Fatalf("RefusedHere(%v, %v) != %v", c.d, c.v, c.want)
		}
	}
	if Suspect(o("http 200")) || !Suspect(o("http 200 wrong-cert")) || !Suspect(o("http 403")) {
		t.Fatal("Suspect: only a 403 or a wrong certificate")
	}
}

// The probe names a certificate for another name (httptest's is for example.com).
func TestProbeWrongCert(t *testing.T) {
	needRoot(t)
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(200) }))
	defer srv.Close()
	_, port, _ := net.SplitHostPort(srv.Listener.Addr().String())
	p := NewProber(2*time.Second, "")
	p.Port = port
	p.Lookup = func(context.Context, string) ([]net.IP, error) { return []net.IP{net.ParseIP("127.0.0.1")}, nil }
	if r := p.Probe(context.Background(), "example.com", "lo"); r.Why != "http 200" {
		t.Fatalf("its own name: %+v", r)
	}
	if r := p.Probe(context.Background(), "blocked-site.com", "lo"); r.Verdict != Open || r.Why != "http 200 wrong-cert" {
		t.Fatalf("another name: %+v", r)
	}
}
