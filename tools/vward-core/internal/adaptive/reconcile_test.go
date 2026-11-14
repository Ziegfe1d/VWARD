package adaptive

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestOwnedImportForgetSave(t *testing.T) {
	dir := t.TempDir()
	shell := filepath.Join(dir, "adaptive-persist.txt")
	os.WriteFile(shell, []byte("a.example.com\nGONE.example.com\nB.Example.com\nnot a name\n"), 0o644)
	o, _ := LoadOwned(filepath.Join(dir, "owned.json"))
	in := map[string]bool{"a.example.com": true, "b.example.com": true, "owner.example.com": true}
	if n := o.ImportShell(shell, in, time.Unix(1, 0)); n != 2 || o.Names["b.example.com"] == nil || o.Names["owner.example.com"] != nil {
		t.Fatalf("import: %d %v", n, o.Names)
	}
	if n := o.ImportShell(shell, in, time.Unix(2, 0)); n != 0 {
		t.Fatal("imported twice")
	}
	if gone := o.Forget(map[string]bool{"a.example.com": true}, time.Unix(100, 0)); len(gone) != 1 || len(o.Names) != 1 || o.Refused["b.example.com"].IsZero() {
		t.Fatalf("forget: %v %v", gone, o.Names)
	}
	if left := o.StillRefused(time.Unix(100, 0).Add(RefuseFor - time.Hour)); left["b.example.com"] != time.Hour {
		t.Fatalf("still refused: %v", left)
	}
	if left := o.StillRefused(time.Unix(100, 0).Add(RefuseFor + time.Hour)); len(left) != 0 || len(o.Refused) != 0 {
		t.Fatalf("refusal over: %v", left)
	}
	o.Refused["b.example.com"] = time.Unix(100, 0)
	if err := o.Save(); err != nil {
		t.Fatal(err)
	}
	back, err := LoadOwned(o.Path)
	if err != nil || len(back.Names) != 1 || back.Names["a.example.com"] == nil || back.Refused["b.example.com"].IsZero() {
		t.Fatalf("reload: %v %v", err, back.Names)
	}
}

func TestDueOrderAndLimit(t *testing.T) {
	o := &Owned{Names: map[string]*Name{
		"new.example.com":   {},
		"old.example.com":   {Checked: time.Unix(100, 0)},
		"fresh.example.com": {Checked: time.Unix(1000, 0)},
	}}
	due := o.Due(time.Unix(1100, 0), 500*time.Second, 1)
	if len(due) != 1 || due[0] != "new.example.com" {
		t.Fatalf("due: %v", due)
	}
	if due := o.Due(time.Unix(1100, 0), 500*time.Second, 8); strings.Join(due, ",") != "new.example.com,old.example.com" {
		t.Fatalf("due all: %v", due)
	}
}

// 3 direct checks in a row, at least MinGap apart; a failure or an unknown starts over.
func TestReconcileStreak(t *testing.T) {
	rc := ReconcileConfig{Every: time.Minute, Batch: 8, Threshold: 3, MinGap: 4 * time.Minute}
	o := &Owned{Names: map[string]*Name{"x.example.com": {}}}
	p := &scripted{ans: map[string][]Verdict{"ppp0 x.example.com": {O, O, B, O, U, O, O, O}}}
	at := func(min int) ([]string, []ReconcileEvent) {
		return Reconcile(context.Background(), o, p, "ppp0", rc, time.Unix(int64(min*60), 0))
	}
	steps := []struct {
		min    int
		event  string
		streak int
	}{
		{0, "DIRECT_CONFIRM", 1},
		{2, "", 1}, // too soon after the last success: not counted
		{6, "DIRECT_FAIL", 0},
		{8, "DIRECT_CONFIRM", 1},
		{13, "DIRECT_UNKNOWN", 0},
		{15, "DIRECT_CONFIRM", 1},
		{20, "DIRECT_CONFIRM", 2},
		{25, "REMOVE", 3},
	}
	for _, s := range steps {
		rm, ev := at(s.min)
		got := ""
		if len(ev) == 1 {
			got = ev[0].Event
		}
		if got != s.event || o.Names["x.example.com"].Streak != s.streak {
			t.Fatalf("minute %d: %q streak %d, want %q %d", s.min, got, o.Names["x.example.com"].Streak, s.event, s.streak)
		}
		if (s.event == "REMOVE") != (len(rm) == 1) {
			t.Fatalf("minute %d: remove %v", s.min, rm)
		}
	}
}

func TestWriterRemoveOnlyIncludes(t *testing.T) {
	w, r := writer(t, cfgText)
	w.Add([]string{"a.example.com", "b.example.com"}, time.Unix(1000, 0))
	r.batches = nil
	b, err := w.Remove([]string{"a.example.com", "not-there.example.com"}, time.Unix(1100, 0))
	if err != nil || len(b.Removed) != 1 || b.Removed[0] != "a.example.com" {
		t.Fatalf("remove: %v %+v", err, b)
	}
	if len(r.batches) != 1 || len(r.batches[0]) != 1 || r.batches[0][0] != "no object-group fqdn AdaptiveAuto include a.example.com" {
		t.Fatalf("batch: %q", r.batches)
	}
	if !contains(r.m.Groups["AdaptiveAuto"].Include, "b.example.com") || len(r.m.RoutesOf("AdaptiveAuto")) != 1 {
		t.Fatal("more than the one name changed")
	}
}

func TestWriterRemoveKeepsLastName(t *testing.T) {
	w, r := writer(t, cfgText)
	b, err := w.Remove([]string{"known.example.net"}, time.Unix(1000, 0))
	if err != nil || len(b.Removed) != 0 || len(r.batches) != 0 || len(r.m.Groups["AdaptiveAuto"].Include) != 1 {
		t.Fatalf("the last name must stay: %v %+v %q", err, b, r.batches)
	}
}

func TestWriterRemoveObserve(t *testing.T) {
	w, r := writer(t, cfgText)
	w.Add([]string{"a.example.com"}, time.Unix(1000, 0))
	r.batches = nil
	w.Observe = true
	b, err := w.Remove([]string{"a.example.com"}, time.Unix(1100, 0))
	if err != nil || len(b.Would) != 1 || len(r.batches) != 0 {
		t.Fatalf("observe: %v %+v", err, b)
	}
}

func contains(a []string, s string) bool {
	for _, x := range a {
		if x == s {
			return true
		}
	}
	return false
}

// A name the owner took out is skipped, not checked, until the refusal runs out.
func TestRefusedNotChecked(t *testing.T) {
	e, p := engine(map[string][]Verdict{"ppp0 x.example.com": {B, B}, "opkgtun4 x.example.com": {O, O}, "ppp0 ya.ru": {O}})
	now := time.Unix(1000, 0)
	e.Now = func() time.Time { return now }
	e.Refuse("x.example.com", time.Hour)
	if r := e.Check(context.Background(), "x.example.com"); r.Outcome != Skip || len(p.calls) != 0 {
		t.Fatalf("refused: %+v %v", r, p.calls)
	}
	now = now.Add(2 * time.Hour)
	if r := e.Check(context.Background(), "x.example.com"); r.Outcome != Add {
		t.Fatalf("after the refusal: %+v", r)
	}
}

// A router that lived before (owner 12.11.2026): on the core's first start every name already in
// AdaptiveAuto is rechecked, as the shell engine rechecked the whole group; names it already owns
// keep their history, and a second call adds nothing.
func TestAdoptGroupOnFirstStart(t *testing.T) {
	dir := t.TempDir()
	o, _ := LoadOwned(filepath.Join(dir, "owned.json"))
	o.Names["kept.example.com"] = &Name{Added: time.Unix(5, 0), Streak: 2}
	in := map[string]bool{"old.example.com": true, "Old2.Example.com.": true, "kept.example.com": true}
	in["new.example.com"] = true
	if n := o.AdoptGroup(in, time.Unix(9, 0)); n != 2 || o.Names["old.example.com"] == nil || o.Names["new.example.com"] == nil || len(o.Names) != 3 {
		t.Fatalf("adopted %d: %v", n, o.Names)
	}
	if o.Names["kept.example.com"].Streak != 2 || !o.Names["kept.example.com"].Added.Equal(time.Unix(5, 0)) {
		t.Fatalf("an owned name lost its history: %+v", o.Names["kept.example.com"])
	}
	if n := o.AdoptGroup(in, time.Unix(10, 0)); n != 0 {
		t.Fatalf("a second adoption added %d", n)
	}
}

type dnsBlocked struct{}

func (dnsBlocked) Probe(context.Context, string, string) ProbeResult {
	return ProbeResult{Unknown, "dns blocked"}
}

// A name DNS filters (0.0.0.0) leaves the group at its first check: VPN gets the same DNS answer.
func TestReconcileDNSBlockedRemoved(t *testing.T) {
	rc := ReconcileConfig{Every: time.Minute, Batch: 8, Threshold: 3, MinGap: 4 * time.Minute}
	o := &Owned{Names: map[string]*Name{"ad.doubleclick.net": {}}}
	rm, ev := Reconcile(context.Background(), o, dnsBlocked{}, "ppp0", rc, time.Unix(60, 0))
	if len(rm) != 1 || rm[0] != "ad.doubleclick.net" || len(ev) != 1 || ev[0].Event != "REMOVE" || ev[0].Why != "dns blocked" {
		t.Fatalf("dns blocked: %v %+v", rm, ev)
	}
}

func vpnRC() ReconcileConfig {
	return ReconcileConfig{Every: time.Minute, Batch: 8, Threshold: 3, MinGap: 4 * time.Minute,
		TunnelDev: "opkgtun4", VPNControl: []string{"ctl.example.org"}}
}

func round(o *Owned, p Prober, rc ReconcileConfig, min int) ([]string, []ReconcileEvent) {
	return Reconcile(context.Background(), o, p, "ppp0", rc, time.Unix(int64(min*60), 0))
}

// fix.39: a name that opens neither directly nor through the VPN 3 rounds in a row (the VPN itself
// working) leaves the group; the reason of the direct failure is kept with the name.
func TestReconcileVPNCheckRemoves(t *testing.T) {
	o := &Owned{Names: map[string]*Name{"ftp.lug.ro": {}}}
	p := &scripted{ans: map[string][]Verdict{"ppp0 ftp.lug.ro": {B}, "opkgtun4 ftp.lug.ro": {B}, "opkgtun4 ctl.example.org": {O}}}
	rc := vpnRC()
	for i, want := range []string{"VPN_FAIL", "VPN_FAIL", "REMOVE"} {
		rm, ev := round(o, p, rc, i*10)
		if len(ev) != 1 || ev[0].Event != want || o.Names["ftp.lug.ro"].VPNFail != i+1 || (want == "REMOVE") != (len(rm) == 1) {
			t.Fatalf("round %d: %+v remove %v, want %s", i, ev, rm, want)
		}
	}
	if o.Names["ftp.lug.ro"].Why != "blocked" {
		t.Fatalf("the reason of the direct failure is kept: %+v", o.Names["ftp.lug.ro"])
	}
}

// A name the VPN opens stays (that is what the group is for) and its count starts over; a VPN
// that does not open the control sites proves nothing; without a VPN device the VPN is not asked.
func TestReconcileVPNCheckKeeps(t *testing.T) {
	o := &Owned{Names: map[string]*Name{"x.example.com": {}}}
	p := &scripted{ans: map[string][]Verdict{"ppp0 x.example.com": {B}, "opkgtun4 x.example.com": {B, B, O, B}, "opkgtun4 ctl.example.org": {O}}}
	rc := vpnRC()
	for i, want := range []int{1, 2, 0, 1} {
		rm, _ := round(o, p, rc, i*10)
		if len(rm) != 0 || o.Names["x.example.com"].VPNFail != want {
			t.Fatalf("round %d: remove %v count %d, want %d", i, rm, o.Names["x.example.com"].VPNFail, want)
		}
	}

	o = &Owned{Names: map[string]*Name{"a.example.com": {}, "b.example.com": {}}}
	p = &scripted{ans: map[string][]Verdict{"ppp0 a.example.com": {B}, "ppp0 b.example.com": {B},
		"opkgtun4 a.example.com": {B}, "opkgtun4 b.example.com": {B}, "opkgtun4 ctl.example.org": {B}}}
	for i := 0; i < 4; i++ {
		rm, ev := round(o, p, rc, i*10)
		if len(rm) != 0 || o.Names["a.example.com"].VPNFail != 0 || len(ev) != 3 || ev[0].Event != "VPN_UNRELIABLE" {
			t.Fatalf("a VPN that does not work: remove %v %+v", rm, ev)
		}
	}
	if n := p.count("opkgtun4 ctl.example.org"); n != 4 {
		t.Fatalf("the VPN is asked about itself once a round: %d", n)
	}

	o = &Owned{Names: map[string]*Name{"x.example.com": {}}}
	p = &scripted{ans: map[string][]Verdict{"ppp0 x.example.com": {B}, "opkgtun4 x.example.com": {B}, "opkgtun4 ctl.example.org": {O}}}
	rc.TunnelDev = ""
	for i := 0; i < 4; i++ {
		if rm, ev := round(o, p, rc, 1000+i*10); len(rm) != 0 || len(ev) != 1 || ev[0].Event != "DIRECT_FAIL" {
			t.Fatalf("no VPN device: %v %+v", rm, ev)
		}
	}
	if p.count("opkgtun4") != 0 {
		t.Fatalf("no VPN device: the VPN was asked: %v", p.calls)
	}
}

// A name that opens directly again forgets its VPN failures.
func TestReconcileDirectOpenClearsVPNCount(t *testing.T) {
	o := &Owned{Names: map[string]*Name{"x.example.com": {VPNFail: 2, LastVPNFail: time.Unix(1, 0), Why: "connect: timeout"}}}
	p := &scripted{ans: map[string][]Verdict{"ppp0 x.example.com": {O}}}
	round(o, p, vpnRC(), 10)
	if n := o.Names["x.example.com"]; n.VPNFail != 0 || n.Why != "" || n.Streak != 1 {
		t.Fatalf("%+v", n)
	}
}

func TestReadModes(t *testing.T) {
	dir := t.TempDir()
	if ReadModes(dir).Observe || ReadModes("").Observe {
		t.Fatal("no files, no directory: write")
	}
	for _, f := range []string{"adaptive.disabled", "core.observe"} {
		os.WriteFile(filepath.Join(dir, f), nil, 0o644)
		if !ReadModes(dir).Observe {
			t.Fatalf("%s: nothing may be written", f)
		}
		os.Remove(filepath.Join(dir, f))
		if ReadModes(dir).Observe {
			t.Fatalf("%s gone: writing again", f)
		}
	}
	// A settings directory that cannot be asked: nothing is written.
	file := filepath.Join(dir, "not-a-dir")
	os.WriteFile(file, nil, 0o644)
	if !ReadModes(file).Observe {
		t.Fatal("an unreadable settings directory must mean «do not write»")
	}
}

func TestDirectWhy(t *testing.T) {
	if got := (Result{"x", Add, "direct: tls: reset; vpn: http 200"}).DirectWhy(); got != "tls: reset" {
		t.Fatalf("%q", got)
	}
	if got := (Result{"x", DirectOK, "http 200"}).DirectWhy(); got != "" {
		t.Fatalf("%q", got)
	}
}
