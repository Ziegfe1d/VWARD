package adaptive

import (
	"bufio"
	"context"
	"crypto/tls"
	"errors"
	"net"
	"os"
	"strings"
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
// with the name, and a HEAD request. Any HTTP answer but 451 is Open. The certificate is
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
	d := net.Dialer{Timeout: p.timeout, Control: bindControl(dev)}
	cctx, cancel := context.WithTimeout(ctx, p.timeout)
	defer cancel()
	raw, err := d.DialContext(cctx, "tcp4", addr)
	if err != nil {
		return classify(err, "connect")
	}
	defer raw.Close()
	_ = raw.SetDeadline(time.Now().Add(p.timeout))
	conn := tls.Client(raw, &tls.Config{ServerName: host, InsecureSkipVerify: true, NextProtos: []string{"http/1.1"}})
	if err := conn.HandshakeContext(cctx); err != nil {
		// The server's own TLS answer «no application protocol»: it is there and speaks, only not
		// HTTP/1.1 - the site opens (tunnel.googlezip.net stayed in the VPN, owner 12.11.2026).
		if strings.Contains(err.Error(), "remote error") && strings.Contains(err.Error(), "no application protocol") {
			return ProbeResult{Open, "tls: no application protocol"}
		}
		return classify(err, "tls")
	}
	if _, err := conn.Write([]byte("HEAD / HTTP/1.1\r\nHost: " + host + "\r\nUser-Agent: Mozilla/5.0\r\nAccept: */*\r\nConnection: close\r\n\r\n")); err != nil {
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
	return ProbeResult{Open, "http " + f[1]}
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
