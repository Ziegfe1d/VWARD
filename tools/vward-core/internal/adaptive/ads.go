package adaptive

import (
	"encoding/json"
	"os"
	"sort"
	"strings"
	"sync"
	"time"
)

// «Реклама и счётчики мимо VPN» (owner 13.11.2026): Autopodbor sends to the VPN whatever opens
// only there, and that takes in ad networks and counters (doubleclick, googlesyndication,
// googleadservices, mixpanel in the owner's group): pages wait for them through the VPN and the
// group of 300 names fills with them. The rule to come: such a name is not sent to the VPN.
//
// New rules start in the sandbox (CLAUDE.md, «сначала песочница»): this release knows «Выкл» and
// «Песочница» only. In the sandbox nothing changes - the working Autopodbor adds and removes as
// before - and the journal says what the rule would have done: WOULD_SKIP_AD for a name on its
// way into the VPN, WOULD_REMOVE_AD for one already there. «Вкл» comes after the owner's router
// has run the sandbox.

type AdsMode string

const (
	AdsOff    AdsMode = "off"
	AdsShadow AdsMode = "shadow"
)

// ReadAdsMode: the Panel's choice, one word in a file. Only «shadow» is understood: a missing or
// unreadable file, and any other word (a later release's «on» on an older core too), is «off».
func ReadAdsMode(path string) AdsMode {
	b, err := os.ReadFile(path)
	if err != nil || len(b) > 64 {
		return AdsOff
	}
	if strings.TrimSpace(string(b)) == string(AdsShadow) {
		return AdsShadow
	}
	return AdsOff
}

// adZones: ad networks and counters - the names browsers and applications call for banners,
// ad auctions and visit counting, never for the page itself. A zone takes its subdomains. Where
// the same company has a site of its own (mixpanel.com, amplitude.com: the owners' dashboards)
// only the counter's names are here.
var adZones = map[string]bool{}

func init() {
	for _, z := range []string{
		// Google: ads.
		"doubleclick.net", "googlesyndication.com", "googleadservices.com", "googletagservices.com",
		"adservice.google.com", "2mdn.net", "admob.com",
		// Google: counters.
		"google-analytics.com", "googletagmanager.com", "app-measurement.com",
		// Ad networks and auctions.
		"adnxs.com", "criteo.com", "criteo.net", "taboola.com", "outbrain.com", "rubiconproject.com",
		"pubmatic.com", "openx.net", "amazon-adsystem.com", "adsrvr.org", "casalemedia.com",
		"smartadserver.com", "moatads.com", "adform.net", "bidswitch.net", "3lift.com", "teads.tv",
		"quantserve.com", "scorecardresearch.com", "ads-twitter.com", "ads.linkedin.com", "an.facebook.com",
		// Ads in applications.
		"applovin.com", "unityads.unity3d.com", "vungle.com", "chartboost.com", "supersonicads.com",
		"inmobi.com", "adcolony.com", "mopub.com", "appsflyersdk.com",
		// Counters and audience trackers.
		"api.mixpanel.com", "api-js.mixpanel.com", "mxpnl.com", "api.amplitude.com", "api2.amplitude.com",
		"api.segment.io", "script.hotjar.com", "static.hotjar.com", "flurry.com", "nr-data.net",
		"browser-intake-datadoghq.com", "clarity.ms", "demdex.net", "omtrdc.net", "2o7.net", "krxd.net",
		"bluekai.com", "crwdcntrl.net", "rlcdn.com", "mathtag.com",
	} {
		adZones[z] = true
	}
}

// AdZone: the ad or counter zone that takes name (the name itself or a parent), or "".
func AdZone(name string) string {
	for n := name; n != ""; {
		if adZones[n] {
			return n
		}
		i := strings.IndexByte(n, '.')
		if i < 0 {
			break
		}
		n = n[i+1:]
	}
	return ""
}

// AdName: an ad name and the zone that took it.
type AdName struct{ Host, Zone string }

// AdsSandbox: the rule in the sandbox. It is asked about what the working Autopodbor does and only
// answers; it holds no reference to the engine or the writer, so nothing it does can change a
// decision. A name is told once (the journal is not filled with repeats); the memory is bounded.
type AdsSandbox struct {
	mu             sync.Mutex
	mode           AdsMode
	since          time.Time
	told           map[string]bool
	skips, removes int
}

const adsToldMax = 4096

// SetMode: true when the mode changed. A change starts the telling over.
func (s *AdsSandbox) SetMode(m AdsMode, now time.Time) bool {
	if m != AdsShadow {
		m = AdsOff
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.mode == "" {
		s.mode = AdsOff
	}
	if s.mode == m {
		return false
	}
	s.mode, s.since, s.told, s.skips, s.removes = m, now, nil, 0, 0
	return true
}

func (s *AdsSandbox) Mode() AdsMode {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.mode == "" {
		return AdsOff
	}
	return s.mode
}

func (s *AdsSandbox) tell(host string) bool {
	if s.told[host] {
		return false
	}
	if s.told == nil || len(s.told) >= adsToldMax {
		s.told = map[string]bool{}
	}
	s.told[host] = true
	return true
}

// WouldSkip: host is on its way into the VPN. In the sandbox: its zone and true when it is an ad
// name not told yet.
func (s *AdsSandbox) WouldSkip(host string) (string, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.mode != AdsShadow {
		return "", false
	}
	z := AdZone(host)
	if z == "" || !s.tell(host) {
		return "", false
	}
	s.skips++
	return z, true
}

// WouldRemove: the names Autopodbor holds in the group. In the sandbox: the ad names among them
// not told yet, in order.
func (s *AdsSandbox) WouldRemove(hosts []string) []AdName {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.mode != AdsShadow {
		return nil
	}
	var out []AdName
	for _, h := range hosts {
		if z := AdZone(h); z != "" && s.tell(h) {
			out = append(out, AdName{h, z})
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Host < out[j].Host })
	s.removes += len(out)
	return out
}

// Counts: what was told since the last call (the hour's summary).
func (s *AdsSandbox) Counts() (skips, removes int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	skips, removes = s.skips, s.removes
	s.skips, s.removes = 0, 0
	return
}

// AdsReport: the sandbox's standing result for the Panel - the names Autopodbor holds in the VPN
// now that the rule would not have there, each with its zone. Not «told once»: the whole picture
// at every look.
type AdsReport struct {
	Mode  AdsMode           `json:"mode"`
	Since time.Time         `json:"since"` // the sandbox runs from (this start of the core or the switch)
	At    time.Time         `json:"at"`
	Ads   map[string]string `json:"ads"`
}

// Report: nil when the sandbox is off.
func (s *AdsSandbox) Report(hosts []string, now time.Time) *AdsReport {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.mode != AdsShadow {
		return nil
	}
	r := &AdsReport{Mode: s.mode, Since: s.since.UTC().Truncate(time.Second), At: now.UTC().Truncate(time.Second), Ads: map[string]string{}}
	for _, h := range hosts {
		if z := AdZone(h); z != "" {
			r.Ads[h] = z
		}
	}
	return r
}

// SaveAdsReport: the report where the Panel reads it (a file in memory, not on the USB drive);
// nil takes the file away. The file is replaced whole, never half-written.
func SaveAdsReport(path string, r *AdsReport) error {
	if path == "" {
		return nil
	}
	if r == nil {
		if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
			return err
		}
		return nil
	}
	b, err := json.Marshal(r)
	if err != nil {
		return err
	}
	tmp := path + ".new"
	if err := os.WriteFile(tmp, append(b, '\n'), 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}
