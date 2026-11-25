package main

import (
	"context"
	"errors"
	"net"
	"sync/atomic"
	"testing"
	"time"

	"github.com/AdguardTeam/dnsproxy/proxy"
	"github.com/AdguardTeam/dnsproxy/upstream"
	"github.com/miekg/dns"
)

func TestPilotScope(t *testing.T) {
	for _, name := range []string{"YouTube.com.", "r1.googlevideo.com.", "www.instagram.com."} {
		if !selected(name) {
			t.Fatalf("pilot omitted %s", name)
		}
	}
	for _, name := range []string{"notyoutube.com.", "youtube.com.example.", "example.org."} {
		if selected(name) {
			t.Fatalf("unexpected DNS scope: %s", name)
		}
	}
	if _, err := tunnelDialer("lo"); err == nil {
		t.Fatal("loopback unexpectedly accepted as a VPN")
	}
}

func TestPilotExchange(t *testing.T) {
	packet, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	listener, err := net.Listen("tcp4", packet.LocalAddr().String())
	if err != nil {
		packet.Close()
		t.Fatal(err)
	}
	handler := dns.HandlerFunc(func(writer dns.ResponseWriter, req *dns.Msg) {
		reply := new(dns.Msg).SetReply(req)
		if _, isUDP := writer.RemoteAddr().(*net.UDPAddr); isUDP {
			reply.Truncated = true
		} else {
			reply.Answer = []dns.RR{&dns.A{
				Hdr: dns.RR_Header{Name: req.Question[0].Name, Rrtype: dns.TypeA, Class: dns.ClassINET, Ttl: 60},
				A:   net.IPv4(203, 0, 113, 8),
			}}
		}
		_ = writer.WriteMsg(reply)
	})
	for _, server := range []*dns.Server{
		{PacketConn: packet, Handler: handler},
		{Listener: listener, Handler: handler},
	} {
		ready := make(chan struct{})
		server.NotifyStartedFunc = func() { close(ready) }
		go func() { _ = server.ActivateAndServe() }()
		<-ready
		t.Cleanup(func() { _ = server.Shutdown() })
	}

	var networks []string
	dialer := &net.Dialer{}
	bound := &tunnelUpstream{address: packet.LocalAddr().String(), dial: func(ctx context.Context, network, addr string) (net.Conn, error) {
		networks = append(networks, network)
		return dialer.DialContext(ctx, network, addr)
	}}
	request := new(dns.Msg).SetQuestion("www.youtube.com.", dns.TypeA)
	response, err := bound.Exchange(request)
	if err != nil || len(response.Answer) != 1 || response.Id != request.Id {
		t.Fatalf("DNS over UDP then TCP: %v %v", response, err)
	}
	if len(networks) != 2 || networks[0] != "udp4" || networks[1] != "tcp4" {
		t.Fatalf("both transports must use the supplied VPN dialer: %v", networks)
	}
}

type testUpstream struct {
	exchanges atomic.Int32
	failed    atomic.Bool
}

func (*testUpstream) Address() string { return "test resolver" }
func (*testUpstream) Close() error    { return nil }

func (u *testUpstream) Exchange(req *dns.Msg) (*dns.Msg, error) {
	u.exchanges.Add(1)
	if u.failed.Load() {
		return nil, errors.New("test tunnel unavailable")
	}

	return new(dns.Msg).SetReply(req), nil
}

func TestPilotListener(t *testing.T) {
	healthy := &testUpstream{}
	failed := &testUpstream{}
	failed.failed.Store(true)
	p, err := newProxy(0, []upstream.Upstream{failed, healthy})
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	if err = p.Start(ctx); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = p.Shutdown(ctx) })

	tcp := p.Addr(proxy.ProtoTCP).(*net.TCPAddr)
	udp := p.Addr(proxy.ProtoUDP).(*net.UDPAddr)
	if !tcp.IP.IsLoopback() || !udp.IP.IsLoopback() {
		t.Fatal("pilot listener is exposed outside loopback")
	}

	query := func(client *dns.Client, address, name string, kind uint16) *dns.Msg {
		t.Helper()
		res, _, queryErr := client.Exchange(new(dns.Msg).SetQuestion(name, kind), address)
		if queryErr != nil {
			t.Fatal(queryErr)
		}

		return res
	}
	client := &dns.Client{Timeout: 2 * time.Second}
	if res := query(client, udp.String(), "example.org.", dns.TypeA); res.Rcode != dns.RcodeRefused {
		t.Fatalf("unrelated DNS query was allowed: %v", res)
	}
	if healthy.exchanges.Load() != 0 || failed.exchanges.Load() != 0 {
		t.Fatal("unrelated request reached an upstream")
	}
	if res := query(client, udp.String(), "www.youtube.com.", dns.TypeA); res.Rcode != dns.RcodeSuccess {
		t.Fatal(res)
	}
	client.Net = "tcp"
	if res := query(client, tcp.String(), "www.instagram.com.", dns.TypeAAAA); res.Rcode != dns.RcodeSuccess {
		t.Fatal(res)
	}
	res := query(client, tcp.String(), healthName, dns.TypeTXT)
	if len(res.Answer) != 1 || res.Answer[0].(*dns.TXT).Txt[0] != "1 1" {
		t.Fatalf("service counters incorrect: %v", res)
	}
	healthy.failed.Store(true)
	if res := query(client, tcp.String(), "www.youtube.com.", dns.TypeA); res.Rcode != dns.RcodeServerFailure {
		t.Fatalf("VPN outage must fail this pilot request: %v", res)
	}
}
