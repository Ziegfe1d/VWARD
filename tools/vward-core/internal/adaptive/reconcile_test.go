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

// fix.39 (owner's journal 12.11.2026): a name that does not open directly is checked through the
// VPN too. Neither path 3 times in a row, at least MinGap apart, with the VPN itself working -
// out of the group (DROP); a VPN that opens it, a VPN that could not be checked or a VPN whose
// control sites fail counts nothing.
func TestReconcileVPNCheck(t *testing.T) {
	rc := ReconcileConfig{Every: time.Minute, Batch: 8, Threshold: 3, MinGap: 4 * time.Minute, TunnelDev: "opkgtun4", VPNControl: []string{"ctl.example.org"}}
	o := &Owned{Names: map[string]*Name{"ntp.example.com": {}}}
	p := &scripted{ans: map[string][]Verdict{
		"ppp0 ntp.example.com":     {B},
		"opkgtun4 ntp.example.com": {B, B, O, B, U, B, B, B},
		"opkgtun4 ctl.example.org": {O, O, B, O}, // asked only when the name failed through the VPN
	}}
	n := o.Names["ntp.example.com"]
	steps := []struct {
		min   int
		event string
		fails int
		down  bool
	}{
		{0, "VPN_FAIL", 1, false},
		{2, "", 1, false},             // too soon after the last counted failure
		{6, "DIRECT_FAIL", 0, false},  // the VPN opens it: it stays, the count starts over
		{12, "DIRECT_FAIL", 0, true},  // the VPN's control site fails: nothing counted
		{18, "DIRECT_FAIL", 0, false}, // the VPN could not be checked: nothing counted
		{24, "VPN_FAIL", 1, false},
		{30, "VPN_FAIL", 2, false},
		{36, "DROP", 3, false},
	}
	for _, s := range steps {
		rm, ev := Reconcile(context.Background(), o, p, "ppp0", rc, time.Unix(int64(s.min*60), 0))
		got, down := "", false
		for _, x := range ev {
			if x.Event == "VPN_DOWN" {
				down = true
			} else {
				got = x.Event
			}
		}
		if got != s.event || n.VPNFail != s.fails || down != s.down {
			t.Fatalf("minute %d: %q fails %d down %v, want %q %d %v (%+v)", s.min, got, n.VPNFail, down, s.event, s.fails, s.down, ev)
		}
		if (s.event == "DROP") != (len(rm) == 1) {
			t.Fatalf("minute %d: remove %v", s.min, rm)
		}
	}
	if n.Why != "blocked" {
		t.Fatalf("the reason of the direct failure is kept: %q", n.Why)
	}
	// A direct success ends the count of failures.
	o = &Owned{Names: map[string]*Name{"x.example.com": {VPNFail: 2, LastVPNFail: time.Unix(1, 0)}}}
	p = &scripted{ans: map[string][]Verdict{"ppp0 x.example.com": {O}}}
	Reconcile(context.Background(), o, p, "ppp0", rc, time.Unix(6000, 0))
	if o.Names["x.example.com"].VPNFail != 0 || p.count("opkgtun4") != 0 {
		t.Fatalf("a name that opens directly is not checked through the VPN: %+v %v", o.Names["x.example.com"], p.calls)
	}
	// Without the VPN's device nothing is asked through it and nothing dropped.
	rc.TunnelDev = ""
	o = &Owned{Names: map[string]*Name{"y.example.com": {VPNFail: 2}}}
	p = &scripted{ans: map[string][]Verdict{"ppp0 y.example.com": {B}}}
	if rm, ev := Reconcile(context.Background(), o, p, "ppp0", rc, time.Unix(6000, 0)); len(rm) != 0 || len(ev) != 1 || ev[0].Event != "DIRECT_FAIL" || len(p.calls) != 1 {
		t.Fatalf("no VPN device: %v %+v %v", rm, ev, p.calls)
	}
}

// The control sites are asked once a round, and only when a name failed through the VPN.
func TestReconcileVPNControlOnce(t *testing.T) {
	rc := ReconcileConfig{Every: time.Minute, Batch: 8, Threshold: 3, MinGap: time.Minute, TunnelDev: "opkgtun4", VPNControl: []string{"ctl.example.org"}}
	o := &Owned{Names: map[string]*Name{"a.example.com": {}, "b.example.com": {}, "c.example.com": {}}}
	p := &scripted{ans: map[string][]Verdict{
		"ppp0 a.example.com": {B}, "ppp0 b.example.com": {B}, "ppp0 c.example.com": {B},
		"opkgtun4 a.example.com": {B}, "opkgtun4 b.example.com": {B}, "opkgtun4 c.example.com": {O},
		"opkgtun4 ctl.example.org": {O},
	}}
	Reconcile(context.Background(), o, p, "ppp0", rc, time.Unix(600, 0))
	if p.count("opkgtun4 ctl.example.org") != 1 || o.Names["a.example.com"].VPNFail != 1 || o.Names["c.example.com"].VPNFail != 0 {
		t.Fatalf("control once: %v", p.calls)
	}
	o = &Owned{Names: map[string]*Name{"c.example.com": {}}}
	p = &scripted{ans: map[string][]Verdict{"ppp0 c.example.com": {B}, "opkgtun4 c.example.com": {O}, "opkgtun4 ctl.example.org": {O}}}
	Reconcile(context.Background(), o, p, "ppp0", rc, time.Unix(600, 0))
	if p.count("opkgtun4 ctl.example.org") != 0 {
		t.Fatalf("no failure through the VPN - no control check: %v", p.calls)
	}
}

func TestNamesCDNAndAds(t *testing.T) {
	for name, want := range map[string]string{
		"e1234.a.akamaiedge.net": "akamaiedge.net", "x.sni.global.fastly.net": "fastly.net", "d111.cloudfront.net": "cloudfront.net",
		"akamai.net": "akamai.net", "notakamai.net": "", "chatgpt.com": "", "fastly.net.example.com": "",
	} {
		if got := SharedCDN(name); got != want {
			t.Fatalf("SharedCDN(%s) = %q, want %q", name, got, want)
		}
	}
	for name, want := range map[string]string{
		"ad.doubleclick.net": "doubleclick.net", "pagead2.googlesyndication.com": "googlesyndication.com",
		"www.googleadservices.com": "googleadservices.com", "api.mixpanel.com": "mixpanel.com", "mixpanel.com": "mixpanel.com",
		"google.com": "", "www.google.com": "", "facebook.com": "", "notdoubleclick.net": "", "segment.com": "", "cdn.segment.com": "cdn.segment.com",
	} {
		if got := AdName(name); got != want {
			t.Fatalf("AdName(%s) = %q, want %q", name, got, want)
		}
	}
	// The list holds names Keenetic could keep (no comment or blank read as a name).
	if len(adNames) < 30 {
		t.Fatalf("ads.txt read short: %d", len(adNames))
	}
	for _, n := range adNames {
		if normalizeName(n) != n {
			t.Fatalf("ads.txt: %q is not a plain name", n)
		}
	}
}

// Marks for the Panel: a content network's common name always, an advert only in the sandbox;
// switched off, the advert marks go. Saved with the names.
func TestOwnedMark(t *testing.T) {
	o, _ := LoadOwned(filepath.Join(t.TempDir(), "owned.json"))
	o.Names = map[string]*Name{"x.sni.global.fastly.net": {}, "ad.doubleclick.net": {}, "chatgpt.com": {}}
	if !o.Mark(false) || o.Names["x.sni.global.fastly.net"].CDN != "fastly.net" || o.Names["ad.doubleclick.net"].Ad != "" || o.Mark(false) {
		t.Fatalf("cdn marks: %+v", o.Names["x.sni.global.fastly.net"])
	}
	if !o.Mark(true) || o.Names["ad.doubleclick.net"].Ad != "doubleclick.net" || o.Names["chatgpt.com"].Ad != "" || strings.Join(o.Ads(), ",") != "ad.doubleclick.net" {
		t.Fatalf("ad marks: %v", o.Ads())
	}
	o.Names["ad.doubleclick.net"].Why, o.Names["ad.doubleclick.net"].VPNFail = "tls: reset", 2
	o.Save()
	back, err := LoadOwned(o.Path)
	if n := back.Names["ad.doubleclick.net"]; err != nil || n.Ad != "doubleclick.net" || n.Why != "tls: reset" || n.VPNFail != 2 || back.Names["x.sni.global.fastly.net"].CDN != "fastly.net" {
		t.Fatalf("reload: %v %+v", err, n)
	}
	if !o.Mark(false) || len(o.Ads()) != 0 {
		t.Fatal("switched off: the advert marks go")
	}
}

// AUTO_VPN carries why the name did not open directly and whether it is an advert.
func TestAddCarriesReasonAndAd(t *testing.T) {
	e, _ := engine(map[string][]Verdict{"ppp0 ad.doubleclick.net": {B, B}, "opkgtun4 ad.doubleclick.net": {O, O}, "ppp0 ya.ru": {O},
		"ppp0 site.example.com": {B, B}, "opkgtun4 site.example.com": {O, O}})
	if r := e.Check(context.Background(), "ad.doubleclick.net"); r.Outcome != Add || r.Direct != "blocked" || r.Ad != "doubleclick.net" {
		t.Fatalf("advert: %+v", r)
	}
	if r := e.Check(context.Background(), "site.example.com"); r.Outcome != Add || r.Direct != "blocked" || r.Ad != "" {
		t.Fatalf("site: %+v", r)
	}
}
