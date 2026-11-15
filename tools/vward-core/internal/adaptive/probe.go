package adaptive

import (
	"bufio"
	"context"
	"crypto/tls"
	"errors"
	"net"
	"os"
	"strings"
	"sync"
	"syscall"
	"time"
)

// Verdict of one check. Unknown is never a reason for a route (the shell engine's rule:
// «could not check» is no failure state).
type Verdict int

const (
	Unknown Verdict = iota // the check did not run or says nothing about the site
	Open                   // the site answered over HTTPS
	Blocked                // no answer: no connection, reset, time limit, TLS failure, 451
)

func (v Verdict) String() string {
	return [...]string{"unknown", "open", "blocked"}[v]
}

type ProbeResult struct {
	Verdict Verdict
	Why     string
}

// NetProber checks over the network. Lookup and Port are for the tests.
type NetProber struct {
	timeout  time.Duration
	resolver *net.Resolver
	Lookup   func(ctx context.Context, host string) ([]net.IP, error)
	Port     string
	mu       sync.Mutex
	srtt     map[string]time.Duration // smoothed connect time of each device (successes only)
}

// The wait for a silent path, measured (fix.39.2, as COW's estimated timeout): six times the
// usual connect time of the device, never below quickFloor (one lost SYN is resent after 1 s and
// must still pass) and never above the whole check. A blocked site that only stays silent is
// decided in about 1.5 s instead of 3 s; before the first measured connection the whole limit.
const quickFloor = 1500 * time.Millisecond

// The «16 KB» block (TSPU since 06.2025: Cloudflare, Hetzner, DigitalOcean... - the connection
// freezes after the first 14-32 KB): an answer is read up to stallCap bytes from the server
// (handshake included); a freeze after stallMin bytes is said in the Why («stall»).
const (
	stallMin = 8 << 10
	stallCap = 40 << 10
)

// quick: the wait for a silent connection or handshake on dev.
func (p *NetProber) quick(dev string) time.Duration {
	p.mu.Lock()
	s := p.srtt[dev]
	p.mu.Unlock()
	if s == 0 {
		return p.timeout
	}
	return clampWait(6*s, p.timeout)
}

func clampWait(w, limit time.Duration) time.Duration {
	if w < quickFloor {
		w = quickFloor
	}
	if w > limit {
		w = limit
	}
	return w
}

func (p *NetProber) measured(dev string, d time.Duration) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.srtt == nil {
		p.srtt = map[string]time.Duration{}
	}
	if s := p.srtt[dev]; s == 0 {
		p.srtt[dev] = d
	} else {
		p.srtt[dev] = (7*s + d) / 8
	}
}

// readCount: the bytes read from the server, TLS included.
type readCount struct {
	net.Conn
	n int
}

func (c *readCount) Read(b []byte) (int, error) {
	n, err := c.Conn.Read(b)
	c.n += n
	return n, err
}

// NewProber: dns "" uses /etc/resolv.conf (the router's own DNS).
func NewProber(timeout time.Duration, dns string) *NetProber {
	r := &net.Resolver{PreferGo: true}
	if dns != "" {
		if _, _, err := net.SplitHostPort(dns); err != nil {
			dns = net.JoinHostPort(dns, "53")
		}
		r.Dial = func(ctx context.Context, network, _ string) (net.Conn, error) {
			var d net.Dialer
			return d.DialContext(ctx, network, dns)
		}
	}
	np := &NetProber{timeout: timeout, resolver: r, Port: "443"}
	np.Lookup = func(ctx context.Context, host string) ([]net.IP, error) {
		return np.resolver.LookupIP(ctx, "ip4", host)
	}
	return np
}

// Probe: one IPv4 address of host, a TCP connection to 443 through dev, a TLS handshake
// with the name, and a GET request (the answer read up to 40 KB). Any HTTP answer but 451 and
// the refusals of the country is Open; a 403, a certificate for another name and a freeze after
// the first kilobytes are said in the Why for the comparison with the VPN. The certificate is
// not checked: only whether the site answers matters, and a router may have no CA list.
func (p *NetProber) Probe(ctx context.Context, host, dev string) ProbeResult {
	if dev == "" {
		return ProbeResult{Unknown, "no device"}
	}
	if _, err := net.InterfaceByName(dev); err != nil {
		return ProbeResult{Unknown, "device " + dev + " missing"}
	}
	rctx, cancel := context.WithTimeout(ctx, p.timeout)
	ips, err := p.Lookup(rctx, host)
	cancel()
	if err != nil || len(ips) == 0 {
		return ProbeResult{Unknown, "no address"}
	}
	// 0.0.0.0 from DNS: a DNS filter blocks the name (AdGuard Home, the provider) -
	// an advert or a tracker, not a site VPN would open: never a reason for a route
	// (ad.doubleclick.net, api.mixpanel.com in the owner's autopick, 12.11.2026).
	if ips[0].IsUnspecified() {
		return ProbeResult{Unknown, "dns blocked"}
	}
	addr := net.JoinHostPort(ips[0].String(), p.Port)
	q := p.quick(dev)
	d := net.Dialer{Timeout: q, Control: bindControl(dev)}
	cctx, cancel := context.WithTimeout(ctx, q)
	defer cancel()
	started := time.Now()
	nc, err := d.DialContext(cctx, "tcp4", addr)
	if err != nil {
		return classify(err, "connect")
	}
	p.measured(dev, time.Since(started))
	raw := &readCount{Conn: nc}
	defer raw.Close()
	_ = raw.SetDeadline(time.Now().Add(q))
	hctx, hcancel := context.WithTimeout(ctx, q)
	defer hcancel()
	conn := tls.Client(raw, &tls.Config{ServerName: host, InsecureSkipVerify: true, NextProtos: []string{"http/1.1"}})
	if err := conn.HandshakeContext(hctx); err != nil {
		// The server itself answered the handshake and refused only the protocol offered (alert
		// 120; tunnel.googlezip.net in the owner's journal 12.11.2026): it is reached - it opens.
		if m := err.Error(); strings.Contains(m, "remote error") && strings.Contains(m, "no application protocol") {
			return ProbeResult{Open, "tls: no application protocol"}
		}
		return classify(err, "tls")
	}
	// The answer may take the whole limit (a slow page is no block).
	_ = raw.SetDeadline(time.Now().Add(p.timeout))
	// The certificate's name (not its chain: a router may have no CA list): a certificate for
	// another name is the mark of a stub - a provider's block page or a spoofed DNS answer.
	// Said in the Why («wrong-cert»); the decision compares it with the VPN (RefusedHere).
	wrongCert := ""
	if cs := conn.ConnectionState(); len(cs.PeerCertificates) > 0 && cs.PeerCertificates[0].VerifyHostname(host) != nil {
		wrongCert = " wrong-cert"
	}
	// GET, not HEAD (fix.39.2): a refusal of the country is said in the body of a 403 (only that
	// body is read; any other answer is closed after its headers).
	if _, err := conn.Write([]byte("GET / HTTP/1.1\r\nHost: " + host + "\r\nUser-Agent: Mozilla/5.0\r\nAccept: */*\r\nConnection: close\r\n\r\n")); err != nil {
		return classify(err, "write")
	}
	br := bufio.NewReader(conn)
	line, err := br.ReadString('\n')
	if err != nil {
		return classify(err, "answer")
	}
	f := strings.Fields(line)
	if len(f) < 2 || !strings.HasPrefix(f[0], "HTTP/") {
		return ProbeResult{Blocked, "not http"}
	}
	if f[1] == "451" {
		return ProbeResult{Blocked, "http 451"}
	}
	// A 403 that names the country is a refusal of the country (owner's router 16.11.2026:
	// api.openai.com «unsupported_country_region_territory»; Cloudflare's 1009 «banned the
	// country or region»). The headers, then at most 32 KiB of the body.
	if f[1] == "403" {
		body := make([]byte, 0, 4096)
		buf := make([]byte, 4096)
		for len(body) < 32<<10 {
			n, err := br.Read(buf)
			body = append(body, buf[:n]...)
			if err != nil {
				break
			}
		}
		if RegionRefusal(string(body)) {
			return ProbeResult{Blocked, "http 403 region"}
		}
	}
	// A redirect to a «not available in your region» page is the site refusing this country:
	// claude.ai answers 302 to anthropic.com/app-unavailable-in-region and stayed direct
	// (owner 12.11.2026). Only the headers are read, at most 40 lines.
	if strings.HasPrefix(f[1], "3") {
		for i := 0; i < 40; i++ {
			h, err := br.ReadString('\n')
			h = strings.TrimSpace(h)
			if h == "" || err != nil {
				break
			}
			if k, v, ok := strings.Cut(h, ":"); ok && strings.EqualFold(strings.TrimSpace(k), "location") && GeoBlockPage(v) {
				return ProbeResult{Blocked, "http " + f[1] + " region"}
			}
		}
	}
	// The refusals above come first (a block is a block whatever the certificate); an answer
	// with a certificate for another name says so, and one that froze after its first kilobytes.
	stall := ""
	if !strings.HasPrefix(f[1], "3") && froze(raw, br, q, 2*p.timeout) {
		stall = " stall"
	}
	return ProbeResult{Open, "http " + f[1] + wrongCert + stall}
}

// froze: the rest of the answer is read up to stallCap bytes from the server, for at most limit;
// true when it stopped (no byte for q) after stallMin bytes - the «16 KB» freeze, not a short
// page, the end of the answer or a slow trickle.
func froze(raw *readCount, br *bufio.Reader, q, limit time.Duration) bool {
	end := time.Now().Add(limit)
	buf := make([]byte, 4096)
	for raw.n < stallCap {
		dl, quiet := time.Now().Add(q), true
		if dl.After(end) {
			dl, quiet = end, false
		}
		_ = raw.SetReadDeadline(dl)
		if _, err := br.Read(buf); err != nil {
			var ne net.Error
			return quiet && raw.n >= stallMin && errors.As(err, &ne) && ne.Timeout()
		}
	}
	return false
}

// regionWords: the words of a refusal of the country in a 403 (OpenAI's API, Cloudflare's 1009
// page, the usual «not available in your country/region» texts). Lower case.
var regionWords = []string{"unsupported_country", "unsupported country", "country, region, or territory",
	"country or region", "not available in your country", "not available in your region",
	"not supported in your country", "not supported in your region", "unavailable in your country",
	"unavailable in your region", "unsupported_region", "region_not_supported", "error code: 1009"}

// RegionRefusal: the answer's text refuses the country.
func RegionRefusal(text string) bool {
	t := strings.ToLower(text)
	for _, w := range regionWords {
		if strings.Contains(t, w) {
			return true
		}
	}
	return false
}

// HTTPCode: the status of an answer's Why («http 403», «http 302 region»), or "".
func HTTPCode(why string) string {
	f := strings.Fields(why)
	if len(f) >= 2 && f[0] == "http" {
		return f[1]
	}
	return ""
}

// WrongCert: the answer came with a certificate for another name.
func WrongCert(r ProbeResult) bool { return hasMark(r.Why, "wrong-cert") }

// Stalled: the answer froze after its first kilobytes (the «16 KB» block).
func Stalled(r ProbeResult) bool { return hasMark(r.Why, "stall") }

func hasMark(why, mark string) bool {
	f := strings.Fields(why)
	for _, w := range f[min(2, len(f)):] {
		if w == mark {
			return true
		}
	}
	return false
}

// Suspect: a direct answer that may be a refusal of this path - a 403, or a certificate for
// another name. Only these are compared with the VPN; any other answer is «opens directly»
// at once, as before (no extra check on the common path).
func Suspect(r ProbeResult) bool {
	return r.Verdict == Open && (HTTPCode(r.Why) == "403" || WrongCert(r) || Stalled(r))
}

// RefusedHere: the site refuses this path and answers the VPN (fix.39.2, owner 16.11.2026):
// a direct 403 and any other answer through the VPN (api.anthropic.com answers 403 «Request
// not allowed» directly, without a word of the country); or a certificate for another name
// directly and the right one through the VPN (a stub of the provider, a spoofed DNS answer).
func RefusedHere(direct, vpn ProbeResult) bool {
	if direct.Verdict != Open || vpn.Verdict != Open || HTTPCode(vpn.Why) == "" {
		return false
	}
	clean := !WrongCert(vpn) && !Stalled(vpn)
	if HTTPCode(direct.Why) == "403" && HTTPCode(vpn.Why) != "403" && clean {
		return true
	}
	// A freeze after the first kilobytes directly and the whole answer through the VPN: the
	// «16 KB» block of the provider (TSPU), not a slow site (that freezes both ways).
	if Stalled(direct) && clean {
		return true
	}
	return WrongCert(direct) && clean
}

// geoMarks: words of the pages sites send a refused country to.
var geoMarks = []string{"unavailable", "unsupported", "not-available", "not_available", "notavailable",
	"restricted", "geoblock", "geo-block", "region-block", "blocked-region", "country-not", "not-supported-country"}

// GeoBlockPage: a redirect target that is a «not available in your region» page.
func GeoBlockPage(location string) bool {
	l := strings.ToLower(location)
	for _, m := range geoMarks {
		if strings.Contains(l, m) {
			return true
		}
	}
	return false
}

// classify: errors of the router itself (no permission, no device, no memory) are Unknown,
// everything the network did is Blocked.
func classify(err error, stage string) ProbeResult {
	var errno syscall.Errno
	if errors.As(err, &errno) {
		switch errno {
		case syscall.EPERM, syscall.EACCES, syscall.ENODEV, syscall.ENOMEM, syscall.ENOBUFS, syscall.EMFILE, syscall.ENFILE:
			return ProbeResult{Unknown, stage + ": " + errno.Error()}
		}
	}
	if errors.Is(err, context.Canceled) {
		return ProbeResult{Unknown, stage + ": canceled"}
	}
	if errors.Is(err, os.ErrDeadlineExceeded) || errors.Is(err, context.DeadlineExceeded) {
		return ProbeResult{Blocked, stage + ": timeout"}
	}
	var ne net.Error
	if errors.As(err, &ne) && ne.Timeout() {
		return ProbeResult{Blocked, stage + ": timeout"}
	}
	msg := err.Error()
	switch {
	case strings.Contains(msg, "reset"):
		return ProbeResult{Blocked, stage + ": reset"}
	case strings.Contains(msg, "refused"):
		return ProbeResult{Blocked, stage + ": refused"}
	case strings.Contains(msg, "EOF"):
		return ProbeResult{Blocked, stage + ": closed"}
	}
	return ProbeResult{Blocked, stage + ": " + shorten(msg)}
}

func shorten(s string) string {
	if i := strings.LastIndex(s, ": "); i >= 0 {
		s = s[i+2:]
	}
	if len(s) > 60 {
		s = s[:60]
	}
	return strings.ReplaceAll(s, "|", "/")
}

// DefaultRouteDev: the device of the IPv4 default route (/proc/net/route).
func DefaultRouteDev() string {
	b, err := os.ReadFile("/proc/net/route")
	if err != nil {
		return ""
	}
	for _, l := range strings.Split(string(b), "\n")[1:] {
		f := strings.Fields(l)
		if len(f) >= 8 && f[1] == "00000000" && f[7] == "00000000" {
			return f[0]
		}
	}
	return ""
}
