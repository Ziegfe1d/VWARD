package adaptive

import (
	"context"
	"net"
	"testing"
	"time"
)

// viaProber: the router's DNS has no address for blocked names; the tunnel's has.
type viaProber struct {
	coded
	via    map[string]string // host -> address through the tunnel
	probed []string
}

func (v *viaProber) LookupVia(_ context.Context, host, dev string) []net.IP {
	if a, ok := v.via[host]; ok {
		return []net.IP{net.ParseIP(a)}
	}
	return nil
}

func (v *viaProber) ProbeAt(_ context.Context, host, dev string, ips []net.IP) ProbeResult {
	v.probed = append(v.probed, dev+" "+host+" "+ips[0].String())
	if host == "dead.example.com" {
		return ProbeResult{Blocked, "connect: timeout"}
	}
	return ProbeResult{Open, "http 200"}
}

// The provider's DNS blocks by name (owner 16.11.2026: www.instagram.com, rutracker.org «имени нет»): in the
// sandbox the name is asked through the tunnel and checked through the VPN; only told, nothing changes.
func TestDNSBlockSandbox(t *testing.T) {
	noAddr := ProbeResult{Unknown, "no address"}
	mk := func(on bool) (*Engine, *viaProber) {
		p := &viaProber{coded: coded{ans: map[string][]ProbeResult{
			"ppp0 www.instagram.com": {noAddr}, "ppp0 rutracker.org": {noAddr}, "ppp0 nosuch.example.com": {noAddr},
			"ppp0 dead.example.com": {noAddr}, "ppp0 ad.doubleclick.net": {noAddr}}},
			via: map[string]string{"www.instagram.com": "157.240.0.35", "rutracker.org": "172.67.182.196", "dead.example.com": "192.0.2.7", "ad.doubleclick.net": "142.250.1.1"}}
		cfg := DefaultConfig()
		cfg.WanDev, cfg.TunnelDev = "ppp0", "opkgtun0"
		cfg.DNSBlock = func() bool { return on }
		return New(cfg, p), p
	}
	e, p := mk(true)
	for host, want := range map[string]string{
		"www.instagram.com":  "instagram.com|the router's DNS has no address; through the tunnel 157.240.0.35; vpn: http 200",
		"rutracker.org":      "rutracker.org|the router's DNS has no address; through the tunnel 172.67.182.196; vpn: http 200",
		"nosuch.example.com": "", // no address through the tunnel either: a name that does not exist
		"dead.example.com":   "", // the tunnel has an address, the site does not open through the VPN
		"ad.doubleclick.net": "", // adverts and counters are not looked at
	} {
		r := e.Check(context.Background(), host)
		if r.Outcome != ProbeUnknown || r.DNSBlock != want {
			t.Fatalf("%s: %+v, want DNSBlock %q and nothing changed", host, r, want)
		}
	}
	if len(p.probed) != 3 || p.probed[0][:9] != "opkgtun0 " {
		t.Fatalf("checked through the VPN at the tunnel's address: %v", p.probed)
	}
	e, p = mk(false)
	if r := e.Check(context.Background(), "www.instagram.com"); r.DNSBlock != "" || len(p.probed) != 0 {
		t.Fatalf("sandbox off: nothing asked: %+v %v", r, p.probed)
	}
}

// LookupVia asks the tunnel's resolvers through the device (here a local DNS server on lo answering one A).
func TestLookupViaDevice(t *testing.T) {
	needRoot(t)
	pc, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer pc.Close()
	go func() {
		buf := make([]byte, 512)
		for {
			n, addr, err := pc.ReadFrom(buf)
			if err != nil {
				return
			}
			q := buf[:n]
			// The question ends after its name and 4 bytes (type, class).
			i := 12
			for i < len(q) && q[i] != 0 {
				i += int(q[i]) + 1
			}
			end := i + 5
			if end > len(q) || q[i+2] != 1 { // A only
				r := append([]byte{}, q[:end]...)
				r[2], r[3] = 0x81, 0x80
				pc.WriteTo(r, addr)
				continue
			}
			r := append([]byte{}, q[:end]...)
			r[2], r[3] = 0x81, 0x80 // response, recursion
			r[6], r[7] = 0, 1       // one answer
			r = append(r, 0xc0, 12, 0, 1, 0, 1, 0, 0, 0, 60, 0, 4, 157, 240, 0, 35)
			pc.WriteTo(r, addr)
		}
	}()
	old := TunnelDNS
	TunnelDNS = []string{pc.LocalAddr().String()}
	defer func() { TunnelDNS = old }()
	p := NewProber(2e9, "")
	ips := p.LookupVia(context.Background(), "www.instagram.com", "lo")
	if len(ips) != 1 || ips[0].String() != "157.240.0.35" {
		t.Fatalf("through the device: %v", ips)
	}
	if ips := p.LookupVia(context.Background(), "www.instagram.com", "nosuchdev0"); ips != nil {
		t.Fatalf("a missing device answers nothing: %v", ips)
	}
}

// A name already in the group the router's DNS has no address for (whatsapp.com on the owner's router,
// 16.11.2026): maintenance tells it too in the sandbox; the name stays, nothing changes.
func TestReconcileDNSBlockSandbox(t *testing.T) {
	p := &viaProber{coded: coded{ans: map[string][]ProbeResult{"ppp0 whatsapp.com": {{Unknown, "no address"}}, "ppp0 gone.example.com": {{Unknown, "no address"}}}},
		via: map[string]string{"whatsapp.com": "157.240.0.53"}}
	own := &Owned{Names: map[string]*Name{"whatsapp.com": {}, "gone.example.com": {}}}
	rc := DefaultReconcile()
	rc.TunnelDev = "opkgtun0"
	rc.DNSBlock = func() bool { return true }
	rm, ev := Reconcile(context.Background(), own, p, "ppp0", rc, time.Unix(600, 0))
	got := map[string]string{}
	for _, e := range ev {
		got[e.Host+" "+e.Event] = e.Why
	}
	if len(rm) != 0 || got["whatsapp.com SANDBOX_DNS_BLOCK"] != "whatsapp.com|in the group, the router's DNS has no address; through the tunnel 157.240.0.53; vpn: http 200" ||
		got["whatsapp.com DIRECT_UNKNOWN"] != "no address" {
		t.Fatalf("told, kept: %v %+v", rm, ev)
	}
	if _, ok := got["gone.example.com SANDBOX_DNS_BLOCK"]; ok {
		t.Fatalf("no address through the tunnel either: nothing told: %+v", ev)
	}
	rc.DNSBlock = func() bool { return false }
	own = &Owned{Names: map[string]*Name{"whatsapp.com": {}}}
	p.coded.ans["ppp0 whatsapp.com"] = []ProbeResult{{Unknown, "no address"}}
	if _, ev := Reconcile(context.Background(), own, p, "ppp0", rc, time.Unix(600, 0)); len(ev) != 1 {
		t.Fatalf("sandbox off: only the unknown check: %+v", ev)
	}
}
