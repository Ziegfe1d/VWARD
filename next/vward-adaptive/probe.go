package main

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

// Prober checks whether host answers through one device.
type Prober interface {
	Probe(ctx context.Context, host, dev string) ProbeResult
}

type netProber struct {
	timeout  time.Duration
	resolver *net.Resolver
}

func newProber(timeout time.Duration, dns string) *netProber {
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
	return &netProber{timeout: timeout, resolver: r}
}

// Probe: one IPv4 address of host, a TCP connection to 443 through dev, a TLS handshake
// with the name, and a HEAD request. Any HTTP answer but 451 is Open. The certificate is
// not checked: only whether the site answers matters, and a router may have no CA list.
func (p *netProber) Probe(ctx context.Context, host, dev string) ProbeResult {
	if dev == "" {
		return ProbeResult{Unknown, "no device"}
	}
	if _, err := net.InterfaceByName(dev); err != nil {
		return ProbeResult{Unknown, "device " + dev + " missing"}
	}
	rctx, cancel := context.WithTimeout(ctx, p.timeout)
	ips, err := p.resolver.LookupIP(rctx, "ip4", host)
	cancel()
	if err != nil || len(ips) == 0 {
		return ProbeResult{Unknown, "no address"}
	}
	addr := net.JoinHostPort(ips[0].String(), "443")
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
		return classify(err, "tls")
	}
	if _, err := conn.Write([]byte("HEAD / HTTP/1.1\r\nHost: " + host + "\r\nUser-Agent: Mozilla/5.0\r\nAccept: */*\r\nConnection: close\r\n\r\n")); err != nil {
		return classify(err, "write")
	}
	line, err := bufio.NewReader(conn).ReadString('\n')
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
	return ProbeResult{Open, "http " + f[1]}
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

// defaultRouteDev: the device of the IPv4 default route (/proc/net/route).
func defaultRouteDev() string {
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
