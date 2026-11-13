// Package adaptive is Autopodbor (AdaptiveAuto) in the routing core: the devices' DNS
// queries are seen on the LAN bridge, a new name is checked directly and through the VPN, and
// one that opens only through the VPN goes into the group Keenetic routes to the VPN. The
// rules are the shell engine's (vward-route-engine.sh handle_new/add_adaptive):
//
//   - the direct check fails twice (a second later) before anything happens;
//   - the direct path itself must work: the control sites answer directly (else nothing is
//     proven about this site);
//   - the VPN must open it twice;
//   - «could not check» (Unknown) is never a reason for a route;
//   - .ru, .рф, .su and the Russian services stay on the provider; names of the owner's lists
//     and Smart DNS names are never taken.
//
// Faster than the shell engine: no process per check, the VPN checks start as soon as the
// first direct check fails, alongside the second direct check and the control sites; a site
// that opens directly is never checked through the VPN.
package adaptive

import (
	"context"
	"strings"
	"sync"
	"time"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/ndm"
)

// Prober checks whether host answers through one device.
type Prober interface {
	Probe(ctx context.Context, host, dev string) ProbeResult
}

type Config struct {
	Group      string        // the group Keenetic routes to the VPN (AdaptiveAuto)
	WanDev     string        // the provider's device (direct checks)
	TunnelDev  string        // the VPN's device
	AllowRU    bool          // .ru and the Russian services may go too (off: the owner's rule)
	Skip       []string      // names never taken (and their subdomains)
	Retry      time.Duration // between the two checks of one path
	OKFor      time.Duration // a site that opened directly is not checked again for this long
	FailFor    time.Duration // a site the VPN did not open either
	UnknownFor time.Duration // a check that could not tell
	Control    []string      // sites that must open directly for a direct failure to count
	ControlFor time.Duration // how long the control answer holds
}

func DefaultConfig() Config {
	return Config{Group: "AdaptiveAuto", Retry: time.Second, OKFor: 6 * time.Hour, FailFor: time.Hour,
		UnknownFor: 10 * time.Minute, Control: []string{"ya.ru", "vk.com"}, ControlFor: 2 * time.Minute}
}

type Outcome string

const (
	Skip           Outcome = "SKIP"           // not a name for Autopodbor
	Known          Outcome = "IN_GROUP"       // already in the group
	Cached         Outcome = "CACHED"         // checked recently
	DirectOK       Outcome = "DIRECT_OK"      // opens directly
	ISPUnreliable  Outcome = "ISP_UNRELIABLE" // the direct path itself does not work now
	TunnelFail     Outcome = "ISP_FAIL_VPN_FAIL"
	TunnelUnstable Outcome = "ISP_FAIL_VPN_UNSTABLE"
	ProbeUnknown   Outcome = "PROBE_UNKNOWN" // could not tell: nothing happens
	Add            Outcome = "AUTO_VPN"      // opens only through the VPN: into the group
)

type Result struct {
	Host    string
	Outcome Outcome
	Why     string
}

// DirectWhy: why the direct check failed, from an AUTO_VPN result («direct: X; vpn: Y»); kept
// with the name (the Panel says it, «the VPN's smart refusal» needs it).
func (r Result) DirectWhy() string {
	rest, ok := strings.CutPrefix(r.Why, "direct: ")
	if !ok {
		return ""
	}
	d, _, _ := strings.Cut(rest, "; vpn: ")
	return d
}

type memo struct {
	until time.Time
	res   Result
}

type Engine struct {
	cfg Config
	p   Prober
	Now func() time.Time

	mu       sync.Mutex
	seen     map[string]memo
	group    map[string]bool // the names of cfg.Group
	other    map[string]string
	smart    map[string]bool
	skip     map[string]bool
	ctrl     memo
	ctrlBusy chan struct{}
}

func New(cfg Config, p Prober) *Engine {
	e := &Engine{cfg: cfg, p: p, Now: time.Now, seen: map[string]memo{}, group: map[string]bool{},
		other: map[string]string{}, smart: map[string]bool{}, skip: map[string]bool{}, ctrlBusy: make(chan struct{}, 1)}
	for _, s := range cfg.Skip {
		if n := normalizeName(s); n != "" {
			e.skip[n] = true
		}
	}
	return e
}

// SetConfig: what the router holds now (read every few minutes and after every write).
func (e *Engine) SetConfig(m *ndm.Model) {
	group, other, smart := map[string]bool{}, map[string]string{}, map[string]bool{}
	for name, g := range m.Groups {
		for _, d := range g.Include {
			if name == e.cfg.Group {
				group[d] = true
			} else {
				other[d] = name
			}
		}
	}
	for _, r := range m.DoH {
		if r.Domain != "" {
			smart[r.Domain] = true
		}
	}
	e.mu.Lock()
	e.group, e.other, e.smart = group, other, smart
	e.mu.Unlock()
}

// InGroup: the group now holds this name or a parent of it.
func (e *Engine) InGroup(host string) bool {
	e.mu.Lock()
	defer e.mu.Unlock()
	return coveredBy(host, e.group) != ""
}

func (e *Engine) remember(r Result, d time.Duration) Result {
	e.mu.Lock()
	e.seen[r.Host] = memo{until: e.Now().Add(d), res: r}
	e.mu.Unlock()
	return r
}

// Refuse: a name the owner took out of the group is not put back for d.
func (e *Engine) Refuse(host string, d time.Duration) {
	e.remember(Result{host, Skip, "taken out by the owner"}, d)
}

// Forget a name (after a write that failed: it is checked again later).
func (e *Engine) Forget(host string) {
	e.mu.Lock()
	delete(e.seen, host)
	e.mu.Unlock()
}

// Prune drops expired results (memory stays bounded).
func (e *Engine) Prune() {
	now := e.Now()
	e.mu.Lock()
	for h, m := range e.seen {
		if now.After(m.until) {
			delete(e.seen, h)
		}
	}
	e.mu.Unlock()
}

// Check decides one asked name. It blocks for the checks it needs.
func (e *Engine) Check(ctx context.Context, raw string) Result {
	h := normalizeName(raw)
	if h == "" {
		return Result{raw, Skip, "not a public name"}
	}
	if !e.cfg.AllowRU && ruZone(h) {
		return Result{h, Skip, "ru zone stays on the provider"}
	}
	if routerOwn(h) {
		return Result{h, Skip, "the router's own service (KeenDNS, cloud) stays on the provider"}
	}
	e.mu.Lock()
	switch {
	case coveredBy(h, e.skip) != "":
		e.mu.Unlock()
		return Result{h, Skip, "skip list"}
	case coveredBy(h, e.group) != "":
		e.mu.Unlock()
		return Result{h, Known, "in " + e.cfg.Group}
	case coveredBy(h, e.smart) != "":
		e.mu.Unlock()
		return Result{h, Skip, "Smart DNS name"}
	}
	for n := h; n != ""; {
		if g, ok := e.other[n]; ok {
			e.mu.Unlock()
			return Result{h, Skip, "in the owner's list " + g}
		}
		_, rest, ok := cut(n)
		if !ok {
			break
		}
		n = rest
	}
	if m, ok := e.seen[h]; ok && e.Now().Before(m.until) {
		e.mu.Unlock()
		if m.res.Outcome == Skip {
			return m.res
		}
		r := m.res
		r.Outcome, r.Why = Cached, string(m.res.Outcome)
		return r
	}
	e.mu.Unlock()

	d1 := e.p.Probe(ctx, h, e.cfg.WanDev)
	switch d1.Verdict {
	case Open:
		return e.remember(Result{h, DirectOK, d1.Why}, e.cfg.OKFor)
	case Unknown:
		return e.remember(Result{h, ProbeUnknown, "direct: " + d1.Why}, e.cfg.UnknownFor)
	}
	// The first direct check failed: the VPN checks start now, alongside the second direct
	// check and the control sites.
	type pair struct{ a, b ProbeResult }
	vpn := make(chan pair, 1)
	go func() {
		a := e.p.Probe(ctx, h, e.cfg.TunnelDev)
		if a.Verdict != Open {
			vpn <- pair{a, ProbeResult{}}
			return
		}
		sleep(ctx, e.cfg.Retry)
		vpn <- pair{a, e.p.Probe(ctx, h, e.cfg.TunnelDev)}
	}()
	sleep(ctx, e.cfg.Retry)
	d2 := e.p.Probe(ctx, h, e.cfg.WanDev)
	ctl := Verdict(Open)
	if d2.Verdict == Blocked {
		ctl = e.control(ctx)
	}
	v := <-vpn
	switch {
	case d2.Verdict == Open:
		return e.remember(Result{h, DirectOK, "second direct check: " + d2.Why}, e.cfg.OKFor)
	case d2.Verdict == Unknown:
		return e.remember(Result{h, ProbeUnknown, "direct retry: " + d2.Why}, e.cfg.UnknownFor)
	case ctl == Blocked:
		return e.remember(Result{h, ISPUnreliable, "the control sites do not open directly either"}, e.cfg.UnknownFor)
	case ctl == Unknown:
		return e.remember(Result{h, ProbeUnknown, "control sites could not be checked"}, e.cfg.UnknownFor)
	case v.a.Verdict == Unknown:
		return e.remember(Result{h, ProbeUnknown, "vpn: " + v.a.Why}, e.cfg.UnknownFor)
	case v.a.Verdict == Blocked:
		return e.remember(Result{h, TunnelFail, "direct: " + d1.Why + "; vpn: " + v.a.Why}, e.cfg.FailFor)
	case v.b.Verdict == Unknown:
		return e.remember(Result{h, ProbeUnknown, "vpn retry: " + v.b.Why}, e.cfg.UnknownFor)
	case v.b.Verdict == Blocked:
		return e.remember(Result{h, TunnelUnstable, "vpn retry: " + v.b.Why}, e.cfg.FailFor)
	}
	return e.remember(Result{h, Add, "direct: " + d1.Why + "; vpn: " + v.a.Why}, e.cfg.FailFor)
}

// control: do the control sites open directly? One check at a time, the answer held for
// ControlFor. Open when one opens; Blocked when all fail; Unknown otherwise.
func (e *Engine) control(ctx context.Context) Verdict {
	e.ctrlBusy <- struct{}{}
	defer func() { <-e.ctrlBusy }()
	e.mu.Lock()
	if e.Now().Before(e.ctrl.until) {
		v := e.ctrl.res.Outcome
		e.mu.Unlock()
		return verdictOf(v)
	}
	e.mu.Unlock()
	res := Blocked
	for _, c := range e.cfg.Control {
		switch e.p.Probe(ctx, c, e.cfg.WanDev).Verdict {
		case Open:
			res = Open
		case Unknown:
			if res == Blocked {
				res = Unknown
			}
		}
		if res == Open {
			break
		}
	}
	e.mu.Lock()
	e.ctrl = memo{until: e.Now().Add(e.cfg.ControlFor), res: Result{Outcome: Outcome(res.String())}}
	e.mu.Unlock()
	return res
}

func verdictOf(o Outcome) Verdict {
	switch string(o) {
	case "open":
		return Open
	case "blocked":
		return Blocked
	}
	return Unknown
}

func cut(n string) (string, string, bool) {
	for i := 0; i < len(n); i++ {
		if n[i] == '.' {
			rest := n[i+1:]
			if !containsDot(rest) {
				return "", "", false
			}
			return n[:i], rest, true
		}
	}
	return "", "", false
}

func containsDot(s string) bool {
	for i := 0; i < len(s); i++ {
		if s[i] == '.' {
			return true
		}
	}
	return false
}

func sleep(ctx context.Context, d time.Duration) {
	if d <= 0 {
		return
	}
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
	case <-t.C:
	}
}
