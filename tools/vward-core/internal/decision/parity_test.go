package decision

import (
	"errors"
	"fmt"
	"math/rand"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// The shell originals: the decisions must be equal byte for byte, refusal codes included.
var lib = func() string {
	p, _ := filepath.Abs("../../../../components/runtime/lib/vward-routing-audit.sh")
	return p
}()

func shells(t *testing.T) [][]string {
	var out [][]string
	if p, err := exec.LookPath("sh"); err == nil {
		out = append(out, []string{p})
	}
	if p, err := exec.LookPath("busybox"); err == nil {
		out = append(out, []string{p, "ash"})
	}
	if len(out) == 0 {
		t.Skip("no shell")
	}
	return out
}

func runShell(t *testing.T, sh []string, fn string, args ...string) (string, int) {
	cmd := exec.Command(sh[0], append(sh[1:], append([]string{"-c", ". \"$0\"; " + fn + " \"$@\"", lib}, args...)...)...)
	cmd.Env = append(os.Environ(), "LC_ALL=C")
	out, err := cmd.Output()
	var ee *exec.ExitError
	if errors.As(err, &ee) {
		return string(out), ee.ExitCode()
	}
	if err != nil {
		t.Fatal(err)
	}
	return string(out), 0
}

func code(err error) int {
	if err == nil {
		return 0
	}
	var e *Error
	if errors.As(err, &e) {
		return e.Code
	}
	return -1
}

// coverage: a parity run proves something only when enough cases were accepted.
type coverage struct{ ok, n int }

func (c *coverage) add(rc int, out string) {
	c.n++
	if rc == 0 && out != "" {
		c.ok++
	}
}

func (c *coverage) check(t *testing.T, name string, min float64) {
	t.Logf("%s: %d of %d cases accepted with output", name, c.ok, c.n)
	if float64(c.ok) < min*float64(c.n) {
		t.Fatalf("%s: only %d of %d cases accepted: the generator tests refusals only", name, c.ok, c.n)
	}
}

func pick(r *rand.Rand, a ...string) string { return a[r.Intn(len(a))] }

var (
	services = []string{"youtube.com", "chatgpt", "a", "x.y", "UPPER", "bad space", "telegram@x", ""}
	targets  = []string{"-", "VPN:OpkgTun4", "VPN:Wireguard1", "VPN:auto", "ISP", "VPN:", "vpn:x"}
	dnses    = []string{"-", "default", "nextdns", "quad9", "", "bad/x"}
	modes    = []string{"auto", "vpn", "dns", "isp", "off", "on", "bogus"}
	revs     = []string{"0", "1", "2", "7", "2147483647", "2147483648", "x", "", "03"}
	domainsP = []string{"example.com", "a.example.com", "b.a.example.com", "youtube.com", "googlevideo.com", "com", "x..y", "UP.com", "a-.b", "ozon.ru"}
)

// ledger: mostly well-formed (unique services, floor <= rev), sometimes broken.
func ledger(r *rand.Rand) (string, map[string]int) {
	var b strings.Builder
	if r.Intn(12) > 0 {
		b.WriteString("schema\t1\n")
	}
	revOf := map[string]int{}
	for _, sid := range services[:4] {
		if r.Intn(2) == 0 {
			continue
		}
		m := pick(r, "auto", "vpn", "dns", "isp", "auto")
		t, d := valid(r, m)
		if r.Intn(25) == 0 {
			t = pick(r, targets...)
		}
		rev := r.Intn(4)
		floor := r.Intn(rev + 1)
		if r.Intn(25) == 0 {
			floor = rev + 1
		}
		revOf[sid] = rev
		fmt.Fprintf(&b, "service\t%s\t%d\t%s\t%s\t%s\t%d\n", sid, rev, m, t, d, floor)
		if r.Intn(30) == 0 {
			fmt.Fprintf(&b, "service\t%s\t%d\t%s\t%s\t%s\t%d\n", sid, rev, m, t, d, floor)
		}
	}
	s := b.String()
	if r.Intn(8) == 0 {
		s = strings.TrimSuffix(s, "\n")
	}
	return s, revOf
}

// valid TARGET/DNS of a mode (ISP/VPN pins, DNS profiles).
func valid(r *rand.Rand, m string) (string, string) {
	switch m {
	case "vpn", "on":
		return pick(r, "VPN:OpkgTun4", "VPN:Wireguard1", "VPN:auto"), "default"
	case "dns":
		return "ISP", pick(r, "nextdns", "quad9")
	case "isp":
		return "ISP", "default"
	}
	return "-", "-"
}

func write(t *testing.T, dir, name, body string) string {
	p := filepath.Join(dir, name)
	if err := os.WriteFile(p, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	return p
}

func TestChoiceParity(t *testing.T) {
	var cov coverage
	defer func() { cov.check(t, "choice", 0.25) }()
	r := rand.New(rand.NewSource(1))
	dir := t.TempDir()
	n := 300
	if testing.Short() {
		n = 60
	}
	for _, sh := range shells(t) {
		for i := 0; i < n; i++ {
			led, revOf := ledger(r)
			sid, act := pick(r, services[:5]...), pick(r, modes...)
			tg, dn := valid(r, act)
			if r.Intn(10) == 0 {
				tg, dn = pick(r, targets...), pick(r, dnses...)
			}
			ex := fmt.Sprint(revOf[sid])
			if r.Intn(8) == 0 {
				ex = pick(r, revs...)
			}
			p := write(t, dir, "ledger", led)
			want, wc := runShell(t, sh, "vward_routing_choice", p, sid, act, tg, dn, ex)
			got, err := Choice(led, sid, act, tg, dn, ex)
			cov.add(wc, want)
			if got != want || code(err) != wc {
				t.Fatalf("%v case %d: choice %q %s %s %s %s %s\nshell rc=%d %q\ngo    rc=%d %q", sh, i, led, sid, act, tg, dn, ex, wc, want, code(err), got)
			}
		}
	}
}

func evidence(r *rand.Rand, rev int) string {
	var b strings.Builder
	if r.Intn(12) > 0 {
		b.WriteString("schema\t1\n")
	}
	n := r.Intn(5)
	for i := 0; i < n; i++ {
		src := pick(r, "M", "S", "A", "A")
		ref := pick(r, "r1", "r2", "domain-list3", "youtube.com", "choice", "x@y")
		tg := pick(r, "VPN:OpkgTun4", "VPN:Wireguard1", "ISP", "ISP")
		dn := pick(r, "default", "default", "nextdns")
		sel := pick(r, "0", "1", "1")
		var kind, member string
		ep := 0
		if src == "A" {
			kind, member = pick(r, "active", "positive", "history", "unknown"), pick(r, "bound", "bound", "excluded", "unknown")
			ep = r.Intn(rev + 2)
		} else {
			kind, member = "explicit", "peer"
			if r.Intn(15) == 0 {
				kind = "active"
			}
		}
		fmt.Fprintf(&b, "%s\t%s\t%s\t%s\t%s\t%s\t%d\t%s\n", src, ref, tg, dn, sel, kind, ep, member)
	}
	return b.String()
}

func TestServicePolicyParity(t *testing.T) {
	var cov coverage
	defer func() { cov.check(t, "policy", 0.25) }()
	r := rand.New(rand.NewSource(2))
	dir := t.TempDir()
	n := 400
	if testing.Short() {
		n = 80
	}
	for _, sh := range shells(t) {
		for i := 0; i < n; i++ {
			rev := r.Intn(4)
			floor := r.Intn(rev + 1)
			m := pick(r, "auto", "vpn", "dns", "isp", "bogus")
			tg, dn := "-", "-"
			switch m {
			case "vpn":
				tg, dn = pick(r, "VPN:OpkgTun4", "VPN:Wireguard1"), "default"
			case "dns":
				tg, dn = "ISP", "nextdns"
			case "isp":
				tg, dn = "ISP", "default"
			}
			ev := evidence(r, rev)
			p := write(t, dir, "evidence", ev)
			rs, fs := fmt.Sprint(rev), fmt.Sprint(floor)
			want, wc := runShell(t, sh, "vward_routing_service_policy", m, tg, dn, rs, fs, p)
			got, err := ServicePolicy(m, tg, dn, rs, fs, ev)
			cov.add(wc, want)
			if got != want || code(err) != wc {
				t.Fatalf("%v case %d: policy %s %s %s %s %s\n%q\nshell rc=%d %q\ngo    rc=%d %q", sh, i, m, tg, dn, rs, fs, ev, wc, want, code(err), got)
			}
		}
	}
}

func TestAuditParity(t *testing.T) {
	var cov coverage
	defer func() { cov.check(t, "audit", 0.25) }()
	r := rand.New(rand.NewSource(3))
	dir := t.TempDir()
	n := 300
	if testing.Short() {
		n = 60
	}
	for _, sh := range shells(t) {
		for i := 0; i < n; i++ {
			var in, sn strings.Builder
			for j := r.Intn(6); j > 0; j-- {
				fmt.Fprintf(&in, "%s\t%s\t%s\t%s\t%s\t%s\t%s\n", pick(r, "M", "S", "A"), pick(r, "r1", "r2", "r3", "youtube.com"),
					pick(r, domainsP[:5]...), pick(r, "exact", "subtree"), pick(r, "ISP", "VPN:OpkgTun4", "VPN:Wireguard1"),
					pick(r, "default", "nextdns"), pick(r, "0", "1"))
			}
			if r.Intn(25) == 0 {
				in.WriteString("Z\tbad\n")
			}
			if r.Intn(15) > 0 {
				fmt.Fprintf(&sn, "snapshot\tg-%d\t%s\n", r.Intn(9), pick(r, "known", "known", "unknown"))
			}
			for _, s := range []string{"M", "S", "A"} {
				if r.Intn(20) > 0 {
					fmt.Fprintf(&sn, "source\t%s\t%s\t%s\n", s, pick(r, "0", "1", "1"), pick(r, "known", "known", "unknown"))
				}
			}
			for _, h := range []string{"DNS", "AGH", "VPN:OpkgTun4", "VPN:Wireguard1"} {
				if r.Intn(10) > 0 {
					fmt.Fprintf(&sn, "health\t%s\t%s\n", h, pick(r, "available", "available", "unavailable", "unknown"))
				}
			}
			for j := r.Intn(4); j > 0; j-- {
				owner := pick(r, "vward", "manual", "unknown")
				perm := "reference"
				if owner == "vward" && r.Intn(2) == 0 {
					perm = "managed"
				}
				fmt.Fprintf(&sn, "route\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n", pick(r, "g1", "g2", "domain-list0"), pick(r, domainsP[:5]...),
					pick(r, "exact", "subtree"), pick(r, "ISP", "VPN:OpkgTun4"), pick(r, "default", "nextdns"), owner, perm)
			}
			pi, ps := write(t, dir, "intents", in.String()), write(t, dir, "snapshot", sn.String())
			want, wc := runShell(t, sh, "vward_routing_audit", pi, ps)
			got, err := Audit(in.String(), sn.String())
			cov.add(wc, want)
			if got != want || code(err) != wc {
				t.Fatalf("%v case %d:\n%s---\n%s\nshell rc=%d\n%s\ngo rc=%d\n%s", sh, i, in.String(), sn.String(), wc, want, code(err), got)
			}
		}
	}
}
