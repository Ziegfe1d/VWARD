package adaptive

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestAdZone(t *testing.T) {
	for name, want := range map[string]string{
		"ad.doubleclick.net":                   "doubleclick.net",
		"doubleclick.net":                      "doubleclick.net",
		"pagead2.googlesyndication.com":        "googlesyndication.com",
		"www.googleadservices.com":             "googleadservices.com",
		"api.mixpanel.com":                     "api.mixpanel.com",
		"www.google-analytics.com":             "google-analytics.com",
		"region1.app-measurement.com":          "app-measurement.com",
		"adservice.google.com":                 "adservice.google.com",
		"mixpanel.com":                         "", // the service's own site, not its counter
		"google.com":                           "",
		"chatgpt.com":                          "",
		"notdoubleclick.net":                   "",
		"doubleclick.net.example.org":          "",
		"googlesyndication.com.evil.example":   "",
		"":                                     "",
		"2.datadog.pool.ntp.org":               "", // a time server: no site at all, the checks' matter
		"browser-intake-datadoghq.com":         "browser-intake-datadoghq.com",
		"x.browser-intake-datadoghq.com":       "browser-intake-datadoghq.com",
		"securepubads.g.doubleclick.net":       "doubleclick.net",
		"stats.g.doubleclick.net":              "doubleclick.net",
		"googleads.g.doubleclick.net":          "doubleclick.net",
		"tpc.googlesyndication.com":            "googlesyndication.com",
		"www.googletagmanager.com":             "googletagmanager.com",
		"firebaseinstallations.googleapis.com": "", // the application itself needs it
	} {
		if got := AdZone(name); got != want {
			t.Errorf("AdZone(%q) = %q, want %q", name, got, want)
		}
	}
}

func TestReadAdsMode(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "adaptive-ads.mode")
	if m := ReadAdsMode(p); m != AdsOff {
		t.Fatalf("no file: %q, want off", m)
	}
	for text, want := range map[string]AdsMode{
		"shadow\n":                        AdsShadow,
		"shadow":                          AdsShadow,
		"  shadow  \r\n":                  AdsShadow,
		"off\n":                           AdsOff,
		"":                                AdsOff,
		"on\n":                            AdsOff, // «Вкл» is not in this release: nothing but the sandbox is understood
		"SHADOW\n":                        AdsOff,
		"shadow from VWARD Panel 13.11\n": AdsOff,
	} {
		if err := os.WriteFile(p, []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
		if m := ReadAdsMode(p); m != want {
			t.Errorf("%q: %q, want %q", text, m, want)
		}
	}
}

func TestAdsSandbox(t *testing.T) {
	s := &AdsSandbox{}
	// Off: silent, whatever the name.
	if z, ok := s.WouldSkip("ad.doubleclick.net"); ok || z != "" {
		t.Fatalf("off: %q %v", z, ok)
	}
	if n := s.WouldRemove([]string{"ad.doubleclick.net"}); len(n) != 0 {
		t.Fatalf("off: %v", n)
	}
	t0 := time.Date(2026, 11, 14, 9, 0, 0, 0, time.UTC)
	if r := s.Report([]string{"ad.doubleclick.net"}, t0); r != nil {
		t.Fatalf("off: a report %+v", r)
	}
	if !s.SetMode(AdsShadow, t0) || s.SetMode(AdsShadow, t0.Add(time.Hour)) || s.Mode() != AdsShadow {
		t.Fatal("SetMode tells a change once")
	}
	// A name on its way into the VPN: told once.
	if z, ok := s.WouldSkip("ad.doubleclick.net"); !ok || z != "doubleclick.net" {
		t.Fatalf("first: %q %v", z, ok)
	}
	if _, ok := s.WouldSkip("ad.doubleclick.net"); ok {
		t.Fatal("the same name twice")
	}
	if _, ok := s.WouldSkip("chatgpt.com"); ok {
		t.Fatal("not an ad name")
	}
	// The names already in the group: the ad ones, in order, each once; one told on its way in is
	// not told again as «would take out».
	got := s.WouldRemove([]string{"z.googlesyndication.com", "chatgpt.com", "ad.doubleclick.net", "api.mixpanel.com"})
	if len(got) != 2 || got[0] != (AdName{"api.mixpanel.com", "api.mixpanel.com"}) || got[1] != (AdName{"z.googlesyndication.com", "googlesyndication.com"}) {
		t.Fatalf("would remove: %v", got)
	}
	if again := s.WouldRemove([]string{"z.googlesyndication.com", "api.mixpanel.com"}); len(again) != 0 {
		t.Fatalf("told twice: %v", again)
	}
	if sk, rm := s.Counts(); sk != 1 || rm != 2 {
		t.Fatalf("counts: %d %d", sk, rm)
	}
	if sk, rm := s.Counts(); sk != 0 || rm != 0 {
		t.Fatalf("counts are an hour's, taken once: %d %d", sk, rm)
	}
	// Switched off and on again: the owner sees the whole picture anew.
	// The standing result: every ad name of the group at every look, told before or not.
	rep := s.Report([]string{"z.googlesyndication.com", "chatgpt.com", "api.mixpanel.com"}, t0.Add(2*time.Hour))
	if rep == nil || !rep.Since.Equal(t0) || !rep.At.Equal(t0.Add(2*time.Hour)) || len(rep.Ads) != 2 ||
		rep.Ads["z.googlesyndication.com"] != "googlesyndication.com" || rep.Ads["api.mixpanel.com"] != "api.mixpanel.com" {
		t.Fatalf("report: %+v", rep)
	}
	p := filepath.Join(t.TempDir(), "ads.json")
	if err := SaveAdsReport(p, rep); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(p)
	if string(b) != `{"mode":"shadow","since":"2026-11-14T09:00:00Z","at":"2026-11-14T11:00:00Z","ads":{"api.mixpanel.com":"api.mixpanel.com","z.googlesyndication.com":"googlesyndication.com"}}`+"\n" {
		t.Fatalf("report file: %s", b)
	}
	if err := SaveAdsReport(p, nil); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(p); !os.IsNotExist(err) {
		t.Fatal("off takes the report away")
	}
	if err := SaveAdsReport(p, nil); err != nil {
		t.Fatalf("no report to take away is no error: %v", err)
	}
	if !s.SetMode(AdsOff, t0) {
		t.Fatal("off is a change")
	}
	if _, ok := s.WouldSkip("x.doubleclick.net"); ok {
		t.Fatal("off after shadow")
	}
	s.SetMode(AdsShadow, time.Now())
	if _, ok := s.WouldSkip("ad.doubleclick.net"); !ok {
		t.Fatal("told anew after off and on")
	}
}

// The sandbox never changes a decision: the working system still sends the name to the VPN, the
// sandbox only says what it would have done.
func TestAdsSandboxLeavesEngineAlone(t *testing.T) {
	ans := func() map[string][]Verdict {
		return map[string][]Verdict{"ppp0 ad.doubleclick.net": {B, B}, "opkgtun4 ad.doubleclick.net": {O, O}, "ppp0 ya.ru": {O}}
	}
	e, _ := engine(ans())
	r := e.Check(context.Background(), "ad.doubleclick.net")
	if r.Outcome != Add {
		t.Fatalf("the working system adds it: %+v", r)
	}
	s := &AdsSandbox{}
	s.SetMode(AdsShadow, time.Now())
	if z, ok := s.WouldSkip(r.Host); !ok || z != "doubleclick.net" {
		t.Fatalf("the sandbox would not: %q %v", z, ok)
	}
	e2, _ := engine(ans())
	if r2 := e2.Check(context.Background(), "ad.doubleclick.net"); r2 != r {
		t.Fatalf("the decision differs: %+v / %+v", r, r2)
	}
}
