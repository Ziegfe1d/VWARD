package decision

import (
	"fmt"
	"testing"
)

func on() map[Source]bool { return map[Source]bool{SrcManual: true, SrcService: true, SrcAuto: true} }

func one(t *testing.T, as []Assignment, d string) Assignment {
	t.Helper()
	for _, a := range as {
		if a.Domain == d {
			return a
		}
	}
	t.Fatalf("no assignment for %s", d)
	return Assignment{}
}

func TestVPNZeroToThreeTunnels(t *testing.T) {
	in := []Intent{{Source: SrcService, Ref: "youtube", Domain: "youtube.com", Kind: KindVPN, Tunnel: "auto"},
		{Source: SrcService, Ref: "claude", Domain: "claude.ai", Kind: KindVPN, Tunnel: "OpkgTun2"}}
	cases := []struct {
		tunnels      []string
		def          string
		yt, claude   Kind
		ytTun, clTun string
		ytWhy, clWhy string
	}{
		{nil, "", KindUnknown, KindUnknown, "", "", "no-tunnel", "no-tunnel"},
		{[]string{"OpkgTun4"}, "OpkgTun4", KindVPN, KindUnknown, "OpkgTun4", "", "service", "tunnel-unknown"},
		{[]string{"OpkgTun4", "OpkgTun2"}, "OpkgTun4", KindVPN, KindVPN, "OpkgTun4", "OpkgTun2", "service", "service"},
		{[]string{"OpkgTun4", "OpkgTun2", "Wireguard1"}, "Wireguard1", KindVPN, KindVPN, "Wireguard1", "OpkgTun2", "service", "service"},
		{[]string{"OpkgTun4", "OpkgTun2", "Wireguard1"}, "", KindUnknown, KindVPN, "", "OpkgTun2", "tunnel-unknown", "service"},
	}
	for i, c := range cases {
		as := Resolve(in, Env{Tunnels: c.tunnels, DefaultTunnel: c.def, SourceOn: on()})
		y, cl := one(t, as, "youtube.com"), one(t, as, "claude.ai")
		if y.Kind != c.yt || y.Tunnel != c.ytTun || y.Reason != c.ytWhy || cl.Kind != c.claude || cl.Tunnel != c.clTun || cl.Reason != c.clWhy {
			t.Fatalf("case %d (%d tunnels): youtube %+v claude %+v", i, len(c.tunnels), y, cl)
		}
	}
}

func TestPrecedenceAndOneAssignment(t *testing.T) {
	in := []Intent{
		{Source: SrcAuto, Ref: "ev1", Domain: "t.me", Kind: KindVPN, Tunnel: "auto"},
		{Source: SrcService, Ref: "telegram", Domain: "t.me", Kind: KindProvider},
		{Source: SrcManual, Ref: "domain-list0", Domain: "t.me", Kind: KindVPN, Tunnel: "OpkgTun2"},
		{Source: SrcAuto, Ref: "ev2", Domain: "a.example", Kind: KindVPN, Tunnel: "auto"},
		{Source: SrcService, Ref: "x", Domain: "b.example", Kind: KindVPN, Tunnel: "auto"},
		{Source: SrcService, Ref: "y", Domain: "b.example", Kind: KindProvider},
	}
	env := Env{Tunnels: []string{"OpkgTun4", "OpkgTun2"}, DefaultTunnel: "OpkgTun4", SourceOn: on()}
	as := Resolve(in, env)
	if len(as) != 3 {
		t.Fatalf("one assignment per domain: %+v", as)
	}
	if a := one(t, as, "t.me"); a.Source != SrcManual || a.Tunnel != "OpkgTun2" {
		t.Fatalf("manual must win: %+v", a)
	}
	if a := one(t, as, "a.example"); a.Kind != KindVPN || a.Reason != "auto-evidence" {
		t.Fatalf("auto: %+v", a)
	}
	if a := one(t, as, "b.example"); a.Kind != KindUnknown || a.Reason != "conflicting-intents" {
		t.Fatalf("two services disagree: no guess: %+v", a)
	}
	// Manual switched off: the service decides; services off too: Autopodbor.
	env.SourceOn = map[Source]bool{SrcManual: false, SrcService: true, SrcAuto: true}
	if a := one(t, Resolve(in, env), "t.me"); a.Source != SrcService || a.Kind != KindProvider {
		t.Fatalf("service second: %+v", a)
	}
	env.SourceOn = map[Source]bool{SrcManual: false, SrcService: false, SrcAuto: true}
	if a := one(t, Resolve(in, env), "t.me"); a.Source != SrcAuto || a.Kind != KindVPN {
		t.Fatalf("auto last: %+v", a)
	}
}

func TestUnknownNeverDecided(t *testing.T) {
	in := []Intent{{Source: SrcService, Ref: "s", Domain: "x.example", Kind: KindVPN, Tunnel: "auto"},
		{Source: SrcAuto, Ref: "e", Domain: "y.example", Kind: KindVPN, Tunnel: "auto", Unknown: true}}
	env := Env{Tunnels: []string{"OpkgTun4"}, DefaultTunnel: "OpkgTun4", SourceOn: map[Source]bool{SrcManual: true, SrcAuto: true}}
	as := Resolve(in, env)
	if a := one(t, as, "x.example"); a.Kind != KindUnknown || a.Reason != "source-unknown" {
		t.Fatalf("unknown switch: %+v", a)
	}
	if a := one(t, as, "y.example"); a.Kind != KindUnknown || a.Reason != "intent-unknown" {
		t.Fatalf("unknown evidence: %+v", a)
	}
}

func TestRuNeverAutopodbor(t *testing.T) {
	in := []Intent{{Source: SrcAuto, Ref: "e", Domain: "api.ozon.ru", Kind: KindVPN, Tunnel: "auto"},
		{Source: SrcAuto, Ref: "e2", Domain: "xn--80aswg.xn--p1ai", Kind: KindVPN, Tunnel: "auto"},
		{Source: SrcManual, Ref: "l", Domain: "kinopoisk.ru", Kind: KindVPN, Tunnel: "auto"}}
	as := Resolve(in, Env{Tunnels: []string{"OpkgTun4"}, DefaultTunnel: "OpkgTun4", SourceOn: on()})
	for _, d := range []string{"api.ozon.ru", "xn--80aswg.xn--p1ai"} {
		if a := one(t, as, d); a.Kind != KindAuto || a.Reason != "ru-excluded" {
			t.Fatalf("%s: %+v", d, a)
		}
	}
	// The owner's manual list may still send a .ru domain through the VPN.
	if a := one(t, as, "kinopoisk.ru"); a.Kind != KindVPN {
		t.Fatalf("manual .ru: %+v", a)
	}
}

func TestDNSLimitAndDeadServer(t *testing.T) {
	var in []Intent
	for i := 0; i < 5; i++ {
		in = append(in, Intent{Source: SrcService, Ref: "ai", Domain: fmt.Sprintf("ai%d.example", i), Kind: KindDNS, Profile: "smart"})
	}
	in = append(in, Intent{Source: SrcManual, Ref: "l", Domain: "zz.example", Kind: KindDNS, Profile: "smart"},
		Intent{Source: SrcService, Ref: "d", Domain: "dead.example", Kind: KindDNS, Profile: "gone"},
		Intent{Source: SrcService, Ref: "u", Domain: "unk.example", Kind: KindDNS, Profile: "never-checked"})
	env := Env{Tunnels: []string{"OpkgTun4"}, DefaultTunnel: "OpkgTun4", SourceOn: on(),
		ProfileAlive: map[string]bool{"smart": true, "gone": false}, DoHUsed: 4, DoHLimit: 8}
	as := Resolve(in, env)
	// 4 rows free: the manual domain first, then the services by name.
	dns, limited := 0, 0
	for _, a := range as {
		if a.Kind == KindDNS {
			dns++
		}
		if a.Reason == "dns-limit:vpn" {
			limited++
		}
	}
	if dns != 4 || limited != 2 || one(t, as, "zz.example").Kind != KindDNS || one(t, as, "ai4.example").Reason != "dns-limit:vpn" {
		t.Fatalf("limit: %+v", as)
	}
	if a := one(t, as, "dead.example"); a.Kind != KindVPN || a.Reason != "dns-dead:vpn" {
		t.Fatalf("dead server falls back with its reason: %+v", a)
	}
	if a := one(t, as, "unk.example"); a.Kind != KindUnknown {
		t.Fatalf("unchecked server: %+v", a)
	}
	env.Fallback = KindProvider
	if a := one(t, Resolve(in, env), "dead.example"); a.Kind != KindProvider || a.Reason != "dns-dead:provider" {
		t.Fatalf("provider fallback: %+v", a)
	}
}
