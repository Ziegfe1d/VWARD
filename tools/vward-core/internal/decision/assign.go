package decision

import (
	"sort"
	"strings"
)

// The owner's routing model (ROADMAP 7, 30.10/08.11): three sources — manual domain lists
// (M) over services (S) over Autopodbor (A, internal name AdaptiveAuto) — and four
// assignments — Auto, VPN (a tunnel), Provider (ISP), DNS (a Smart DNS profile). One domain
// gets exactly one assignment; every doubt is Unknown and is never written.

type Source byte

const (
	SrcManual  Source = 'M'
	SrcService Source = 'S'
	SrcAuto    Source = 'A'
)

func (s Source) rank() int {
	switch s {
	case SrcManual:
		return 0
	case SrcService:
		return 1
	}
	return 2
}

type Kind string

const (
	KindAuto     Kind = "auto"
	KindVPN      Kind = "vpn"
	KindProvider Kind = "isp"
	KindDNS      Kind = "dns"
	KindUnknown  Kind = "unknown"
)

// Intent: one source asks for one domain.
type Intent struct {
	Source  Source
	Ref     string // list / service / evidence id
	Domain  string // lower case
	Kind    Kind
	Tunnel  string // VPN: tunnel id, "auto" = the default tunnel
	Profile string // DNS: Smart DNS profile id
	Unknown bool   // the source could not prove this intent (state unread, proof expired)
}

// Env: what the decision may rely on, read once per request.
type Env struct {
	Tunnels       []string        // tunnels that exist, any number (0, 1, 2, 3, ...)
	DefaultTunnel string          // "" = none chosen
	SourceOn      map[Source]bool // the three switches; a missing source is unknown
	ProfileAlive  map[string]bool // Smart DNS profile -> its server answers; missing = unknown
	DoHUsed       int             // rows already taken by others (foreign rows count)
	DoHLimit      int             // Keenetic: 8
	Fallback      Kind            // what a DNS domain falls back to when its server is dead or no room: KindAuto or KindProvider
}

// Assignment: the single decision for one domain.
type Assignment struct {
	Domain  string
	Kind    Kind
	Tunnel  string // resolved tunnel for VPN
	Profile string
	Source  Source
	Ref     string
	Reason  string // why (always set): "manual", "service", "auto-evidence", "dns-limit", "dns-dead", "ru-excluded", ...
}

// ruZone: domains Autopodbor never takes (owner: «.ru не попадает в Автоподбор»).
func ruZone(d string) bool {
	for _, z := range []string{".ru", ".xn--p1ai", ".su", ".xn--d1acj3b"} {
		if strings.HasSuffix(d, z) || d == z[1:] {
			return true
		}
	}
	return false
}

// Resolve gives every domain one assignment. Order: the strongest source wins (M > S > A);
// inside a source, conflicting intents for one domain are Unknown (no guess); a domain of
// an unknown source switch or an unknown intent is Unknown. DNS rows are counted against the
// Keenetic limit in a stable order (M first, then S, then by domain); a domain without a row
// or with a dead server falls back with the reason.
func Resolve(intents []Intent, env Env) []Assignment {
	byDomain := map[string][]Intent{}
	for _, in := range intents {
		byDomain[in.Domain] = append(byDomain[in.Domain], in)
	}
	domains := make([]string, 0, len(byDomain))
	for d := range byDomain {
		domains = append(domains, d)
	}
	sort.Strings(domains)
	tunnelOK := map[string]bool{}
	for _, t := range env.Tunnels {
		tunnelOK[t] = true
	}
	limit := env.DoHLimit
	if limit <= 0 {
		limit = 8
	}
	out := make([]Assignment, 0, len(domains))
	var dnsWanted []int
	for _, d := range domains {
		list := byDomain[d]
		a := Assignment{Domain: d, Kind: KindAuto, Reason: "no-intent"}
		// An unknown switch of a source that has an intent here: nothing is decided.
		unknown := ""
		for _, in := range list {
			on, known := env.SourceOn[in.Source]
			if !known {
				unknown = "source-unknown"
			} else if on && in.Unknown {
				unknown = "intent-unknown"
			}
		}
		if unknown != "" {
			out = append(out, Assignment{Domain: d, Kind: KindUnknown, Reason: unknown})
			continue
		}
		best := -1
		var top []Intent
		for _, in := range list {
			if !env.SourceOn[in.Source] {
				continue
			}
			if in.Source == SrcAuto && ruZone(d) {
				continue
			}
			r := in.Source.rank()
			if best == -1 || r < best {
				best, top = r, nil
			}
			if r == best {
				top = append(top, in)
			}
		}
		if len(top) == 0 {
			reason := "no-active-source"
			for _, in := range list {
				if in.Source == SrcAuto && ruZone(d) && env.SourceOn[SrcAuto] {
					reason = "ru-excluded"
				}
			}
			a.Reason = reason
			out = append(out, a)
			continue
		}
		// Equal-rank intents must agree on one path.
		first := top[0]
		for _, in := range top[1:] {
			if in.Kind != first.Kind || in.Tunnel != first.Tunnel || in.Profile != first.Profile {
				first.Kind = KindUnknown
			}
		}
		a.Source, a.Ref = first.Source, first.Ref
		switch first.Kind {
		case KindUnknown:
			a.Kind, a.Reason = KindUnknown, "conflicting-intents"
		case KindAuto:
			a.Kind, a.Reason = KindAuto, "auto"
		case KindProvider:
			a.Kind, a.Reason = KindProvider, sourceReason(first.Source)
		case KindVPN:
			t := first.Tunnel
			if t == "" || t == "auto" {
				t = env.DefaultTunnel
			}
			switch {
			case len(env.Tunnels) == 0:
				a.Kind, a.Reason = KindUnknown, "no-tunnel"
			case t == "" || !tunnelOK[t]:
				a.Kind, a.Reason = KindUnknown, "tunnel-unknown"
			default:
				a.Kind, a.Tunnel, a.Reason = KindVPN, t, sourceReason(first.Source)
				if first.Source == SrcAuto {
					a.Reason = "auto-evidence"
				}
			}
		case KindDNS:
			a.Kind, a.Profile, a.Reason = KindDNS, first.Profile, sourceReason(first.Source)
			dnsWanted = append(dnsWanted, len(out))
		}
		out = append(out, a)
	}
	// Smart DNS rows: stable order, the limit counts rows of others too.
	sort.SliceStable(dnsWanted, func(i, j int) bool {
		x, y := out[dnsWanted[i]], out[dnsWanted[j]]
		if x.Source.rank() != y.Source.rank() {
			return x.Source.rank() < y.Source.rank()
		}
		return x.Domain < y.Domain
	})
	free := limit - env.DoHUsed
	for _, i := range dnsWanted {
		a := &out[i]
		alive, known := env.ProfileAlive[a.Profile]
		switch {
		case !known:
			a.Kind, a.Reason = KindUnknown, "dns-server-unknown"
		case !alive:
			fallback(a, env, "dns-dead")
		case free <= 0:
			fallback(a, env, "dns-limit")
		default:
			free--
		}
	}
	return out
}

func fallback(a *Assignment, env Env, why string) {
	a.Profile = ""
	switch env.Fallback {
	case KindProvider:
		a.Kind, a.Reason = KindProvider, why+":provider"
	default:
		if env.DefaultTunnel != "" {
			a.Kind, a.Tunnel, a.Reason = KindVPN, env.DefaultTunnel, why+":vpn"
		} else {
			a.Kind, a.Reason = KindAuto, why+":auto"
		}
	}
}

func sourceReason(s Source) string {
	switch s {
	case SrcManual:
		return "manual"
	case SrcService:
		return "service"
	}
	return "auto-evidence"
}
