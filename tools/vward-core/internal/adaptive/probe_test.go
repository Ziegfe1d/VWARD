package adaptive

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"
)

func local(t *testing.T, code int) (*NetProber, func()) {
	t.Helper()
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(code) }))
	_, port, _ := net.SplitHostPort(srv.Listener.Addr().String())
	p := NewProber(2*time.Second, "")
	p.Port = port
	p.Lookup = func(context.Context, string) ([]net.IP, error) { return []net.IP{net.ParseIP("127.0.0.1")}, nil }
	return p, srv.Close
}

func needRoot(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Skip("binding a socket to a device needs root")
	}
}

func TestProbeOverDevice(t *testing.T) {
	needRoot(t)
	p, done := local(t, 403)
	defer done()
	if r := p.Probe(context.Background(), "site.example.com", "lo"); r.Verdict != Open {
		t.Fatalf("an HTTP answer (403) means it opens: %+v", r)
	}
	p451, done451 := local(t, 451)
	defer done451()
	if r := p451.Probe(context.Background(), "site.example.com", "lo"); r.Verdict != Blocked {
		t.Fatalf("451 is a block: %+v", r)
	}
	l, _ := net.Listen("tcp4", "127.0.0.1:0")
	_, port, _ := net.SplitHostPort(l.Addr().String())
	l.Close()
	p.Port = port
	if r := p.Probe(context.Background(), "site.example.com", "lo"); r.Verdict != Blocked {
		t.Fatalf("a refused connection is a failure: %+v", r)
	}
}

func TestProbeUnknownWhenItCannotRun(t *testing.T) {
	p, done := local(t, 200)
	defer done()
	if r := p.Probe(context.Background(), "site.example.com", "nosuchdev0"); r.Verdict != Unknown {
		t.Fatalf("a missing device says nothing about the site: %+v", r)
	}
	p.Lookup = func(context.Context, string) ([]net.IP, error) { return nil, &net.DNSError{Err: "no such host"} }
	if r := p.Probe(context.Background(), "site.example.com", "lo"); r.Verdict != Unknown {
		t.Fatalf("no address says nothing about the site: %+v", r)
	}
}

// A redirect to a «not available in your region» page is a refusal (claude.ai → anthropic.com/
// app-unavailable-in-region stayed direct, owner 12.11.2026); an ordinary redirect opens.
func TestProbeRegionRedirect(t *testing.T) {
	needRoot(t)
	for _, c := range []struct {
		loc  string
		want Verdict
	}{{"https://www.anthropic.com/app-unavailable-in-region", Blocked}, {"https://www.example.com/en/", Open}} {
		loc := c.loc
		srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Location", loc)
			w.WriteHeader(302)
		}))
		_, port, _ := net.SplitHostPort(srv.Listener.Addr().String())
		p := NewProber(2*time.Second, "")
		p.Port = port
		p.Lookup = func(context.Context, string) ([]net.IP, error) { return []net.IP{net.ParseIP("127.0.0.1")}, nil }
		if r := p.Probe(context.Background(), "claude.ai", "lo"); r.Verdict != c.want {
			t.Fatalf("302 to %s: %+v, want %v", loc, r, c.want)
		}
		srv.Close()
	}
}

func TestGeoBlockPage(t *testing.T) {
	for loc, want := range map[string]bool{
		"https://www.anthropic.com/app-unavailable-in-region": true,
		"/unsupported_country":                                 true,
		"https://example.com/login?next=/":                     false,
		"https://www.google.com/":                              false,
	} {
		if GeoBlockPage(loc) != want {
			t.Fatalf("%s: want %v", loc, want)
		}
	}
}

// A name DNS answers with 0.0.0.0 is filtered (an advert): unknown, never a route.
func TestProbeDNSBlocked(t *testing.T) {
	needRoot(t)
	p, done := local(t, 200)
	defer done()
	p.Lookup = func(context.Context, string) ([]net.IP, error) { return []net.IP{net.ParseIP("0.0.0.0")}, nil }
	if r := p.Probe(context.Background(), "ad.doubleclick.net", "lo"); r.Verdict != Unknown || r.Why != "dns blocked" {
		t.Fatalf("0.0.0.0: %+v", r)
	}
}
