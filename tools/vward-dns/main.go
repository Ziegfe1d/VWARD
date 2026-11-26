// vward-dns is the local resolver for VWARD's per-domain DNS pilot.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net"
	"net/netip"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/AdguardTeam/dnsproxy/proxy"
	"github.com/AdguardTeam/dnsproxy/upstream"
	"github.com/miekg/dns"
)

const (
	defaultPort   = 65153
	probeDeadline = 7 * time.Second
	healthName    = "health.vward-dns.invalid."
)

var domains = []string{
	"youtube.com", "youtu.be", "youtube-nocookie.com", "googlevideo.com",
	"ytimg.com", "ggpht.com", "instagram.com", "cdninstagram.com",
}

var resolvers = []string{"8.8.8.8:53", "1.1.1.1:53"}
var routerLoopback = netip.AddrFrom4([4]byte{127, 0, 0, 1})

func selected(name string) bool {
	name = strings.ToLower(strings.TrimSuffix(name, "."))
	for _, domain := range domains {
		if name == domain || strings.HasSuffix(name, "."+domain) {
			return true
		}
	}

	return false
}

type dialContext func(context.Context, string, string) (net.Conn, error)

type pilotStats struct {
	youtube   atomic.Uint64
	instagram atomic.Uint64
}

func (s *pilotStats) count(response *dns.Msg) {
	if response == nil || response.Rcode != dns.RcodeSuccess || len(response.Question) != 1 {
		return
	}
	switch strings.ToLower(response.Question[0].Name) {
	case "www.youtube.com.":
		s.youtube.Add(1)
	case "www.instagram.com.":
		s.instagram.Add(1)
	}
}

// tunnelUpstream keeps both the initial UDP exchange and its TCP retry on the
// same interface. There is no unbound retry or system-resolver bootstrap.
type tunnelUpstream struct {
	address string
	dial    dialContext
}

func (u *tunnelUpstream) Address() string { return u.address }
func (u *tunnelUpstream) Close() error    { return nil }

func (u *tunnelUpstream) Exchange(request *dns.Msg) (*dns.Msg, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 2500*time.Millisecond)
	defer cancel()

	query := request.Copy()
	query.Id = dns.Id()
	for _, transport := range []string{"udp", "tcp"} {
		response, err := u.exchange(ctx, transport, query)
		if err != nil {
			return nil, err
		}
		if response.Truncated && transport == "udp" {
			continue
		}
		if response.Truncated || (response.Rcode != dns.RcodeSuccess && response.Rcode != dns.RcodeNameError) {
			return nil, fmt.Errorf("upstream DNS status %d or truncated TCP response", response.Rcode)
		}
		response.Id = request.Id

		return response, nil
	}

	return nil, errors.New("no complete DNS response")
}

func (u *tunnelUpstream) exchange(ctx context.Context, transport string, query *dns.Msg) (*dns.Msg, error) {
	conn, err := u.dial(ctx, transport+"4", u.address)
	if err != nil {
		return nil, err
	}
	defer conn.Close()

	client := &dns.Client{Net: transport, Timeout: 2500 * time.Millisecond}
	response, _, err := client.ExchangeWithConnContext(ctx, query, &dns.Conn{Conn: conn})
	if err != nil {
		return nil, err
	}
	if transport == "udp" && response.Response && response.Truncated {
		return response, nil
	}
	if !response.Response || len(response.Question) != 1 ||
		!strings.EqualFold(response.Question[0].Name, query.Question[0].Name) ||
		response.Question[0].Qtype != query.Question[0].Qtype ||
		response.Question[0].Qclass != query.Question[0].Qclass {
		return nil, errors.New("upstream response does not match the query")
	}

	return response, nil
}

func tunnelDialer(device string) (dialContext, error) {
	iface, err := net.InterfaceByName(device)
	if err != nil {
		return nil, err
	}
	if iface.Flags&net.FlagPointToPoint == 0 || iface.Flags&net.FlagLoopback != 0 {
		return nil, fmt.Errorf("%s is not a point-to-point tunnel", device)
	}

	dialer := &net.Dialer{Control: func(_, _ string, socket syscall.RawConn) error {
		var bindErr error
		err := socket.Control(func(fd uintptr) {
			bindErr = syscall.SetsockoptString(int(fd), syscall.SOL_SOCKET, syscall.SO_BINDTODEVICE, device)
		})

		return errors.Join(err, bindErr)
	}}

	return dialer.DialContext, nil
}

func newProxy(address netip.Addr, port int, servers []upstream.Upstream) (*proxy.Proxy, error) {
	stats := &pilotStats{}
	return proxy.New(&proxy.Config{
		UDPListenAddr:  []*net.UDPAddr{{IP: address.AsSlice(), Port: port}},
		TCPListenAddr:  []*net.TCPAddr{{IP: address.AsSlice(), Port: port}},
		UpstreamConfig: &proxy.UpstreamConfig{Upstreams: servers},
		MaxGoroutines:  16,
		Logger:         slog.New(slog.DiscardHandler),
		RequestHandler: func(p *proxy.Proxy, request *proxy.DNSContext) error {
			questions := request.Req.Question
			peer := request.Addr.Addr().Unmap()
			if (peer != address && peer != routerLoopback) ||
				request.Req.Opcode != dns.OpcodeQuery || len(questions) != 1 ||
				questions[0].Qclass != dns.ClassINET {
				request.Res = new(dns.Msg).SetRcode(request.Req, dns.RcodeRefused)

				return nil
			}
			if strings.EqualFold(questions[0].Name, healthName) && questions[0].Qtype == dns.TypeTXT {
				request.Res = new(dns.Msg).SetReply(request.Req)
				request.Res.Answer = []dns.RR{&dns.TXT{
					Hdr: dns.RR_Header{Name: healthName, Rrtype: dns.TypeTXT, Class: dns.ClassINET},
					Txt: []string{fmt.Sprintf("%d %d", stats.youtube.Load(), stats.instagram.Load())},
				}}

				return nil
			}
			if !selected(questions[0].Name) {
				request.Res = new(dns.Msg).SetRcode(request.Req, dns.RcodeRefused)

				return nil
			}
			err := p.Resolve(request)
			if err == nil {
				stats.count(request.Res)
			}

			return err
		},
	})
}

func serve(device string, address netip.Addr, port int) error {
	dial, err := tunnelDialer(device)
	if err != nil {
		return err
	}
	servers := make([]upstream.Upstream, 0, len(resolvers))
	for _, resolver := range resolvers {
		servers = append(servers, &tunnelUpstream{address: resolver, dial: dial})
	}

	server, err := newProxy(address, port, servers)
	if err != nil {
		return err
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, os.Interrupt)
	defer stop()
	if err = server.Start(ctx); err != nil {
		return err
	}
	fmt.Printf("vward-dns listening on %s:%d, tunnel=%s\n", address, port, device)
	<-ctx.Done()

	shutdown, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	return server.Shutdown(shutdown)
}

// Probe both services through the pilot listener or Keenetic :53.
func probe(address string) error {
	for _, host := range []string{"www.youtube.com.", "www.instagram.com."} {
		query := new(dns.Msg).SetQuestion(host, dns.TypeA)
		client := &dns.Client{Timeout: probeDeadline}
		response, _, err := client.Exchange(query, address)
		if err != nil {
			return fmt.Errorf("%s: %w", host, err)
		}
		if response.Truncated {
			client.Net = "tcp"
			response, _, err = client.Exchange(query, address)
			if err != nil {
				return fmt.Errorf("%s over TCP: %w", host, err)
			}
		}
		ok := false
		for _, answer := range response.Answer {
			if a, isA := answer.(*dns.A); isA && a.A.IsGlobalUnicast() && !a.A.IsPrivate() {
				ok = true
				break
			}
		}
		if response.Rcode != dns.RcodeSuccess || !ok {
			return fmt.Errorf("%s: no public IPv4 answer (DNS status %d)", host, response.Rcode)
		}
		fmt.Printf("dns-ok %s\n", host)
	}

	return nil
}

func health(address string) error {
	query := new(dns.Msg).SetQuestion(healthName, dns.TypeTXT)
	client := &dns.Client{Timeout: time.Second}
	response, _, err := client.Exchange(query, address)
	if err != nil {
		return err
	}
	if response.Rcode != dns.RcodeSuccess || len(response.Answer) != 1 {
		return errors.New("vward-dns health record missing")
	}
	record, ok := response.Answer[0].(*dns.TXT)
	if !ok || !strings.EqualFold(record.Hdr.Name, healthName) || len(record.Txt) != 1 {
		return errors.New("invalid vward-dns health record")
	}
	fields := strings.Fields(record.Txt[0])
	if len(fields) != 2 {
		return errors.New("invalid vward-dns counters")
	}
	for _, field := range fields {
		if _, err = strconv.ParseUint(field, 10, 64); err != nil {
			return err
		}
	}
	fmt.Println(strings.Join(fields, " "))

	return nil
}

func run(args []string) error {
	if len(args) == 1 && args[0] == "domains" {
		fmt.Println(strings.Join(domains, "\n"))

		return nil
	}
	if len(args) == 0 || (args[0] != "serve" && args[0] != "probe" && args[0] != "health") {
		return errors.New("usage: vward-dns domains | serve -tunnel DEVICE | probe | health [-address IPv4] [-port PORT]")
	}
	cmd := flag.NewFlagSet(args[0], flag.ContinueOnError)
	port := cmd.Int("port", defaultPort, "DNS port")
	host := cmd.String("address", routerLoopback.String(), "local DNS IPv4 address")
	device := cmd.String("tunnel", "", "Linux tunnel interface")
	if err := cmd.Parse(args[1:]); err != nil {
		return err
	}
	if cmd.NArg() != 0 || *port < 1 || *port > 65535 {
		return errors.New("invalid port or extra arguments")
	}
	address, err := netip.ParseAddr(*host)
	if err != nil || !address.Is4() || (!address.IsGlobalUnicast() && address != routerLoopback) {
		return errors.New("a specific IPv4 DNS address is required")
	}
	endpoint := net.JoinHostPort(address.String(), strconv.Itoa(*port))
	if args[0] == "probe" {
		return probe(endpoint)
	}
	if args[0] == "health" {
		return health(endpoint)
	}
	if *device == "" || *port < 1024 || *port == 65053 {
		return errors.New("a tunnel and an unreserved DNS port are required")
	}

	return serve(*device, address, *port)
}

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
