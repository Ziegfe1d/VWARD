package adaptive

import (
	_ "embed"
	"strings"
)

// normalizeName: lower case, no trailing dot; "" when the name is not one Keenetic takes in
// «object-group fqdn ... include» or not a public site.
func normalizeName(s string) string {
	s = strings.TrimSuffix(strings.ToLower(strings.TrimSpace(s)), ".")
	if len(s) < 4 || len(s) > 253 {
		return ""
	}
	labels := strings.Split(s, ".")
	if len(labels) < 2 {
		return ""
	}
	for _, l := range labels {
		if l == "" || len(l) > 63 || l[0] == '-' || l[len(l)-1] == '-' {
			return ""
		}
		for i := 0; i < len(l); i++ {
			c := l[i]
			if !(c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '-') {
				return ""
			}
		}
	}
	tld := labels[len(labels)-1]
	if len(tld) < 2 {
		return ""
	}
	for i := 0; i < len(tld); i++ {
		if tld[i] < 'a' || tld[i] > 'z' {
			if !strings.HasPrefix(tld, "xn--") {
				return ""
			}
		}
	}
	for _, local := range []string{"local", "lan", "home", "arpa", "internal", "localdomain", "localhost", "intranet", "corp", "test", "invalid", "example"} {
		if tld == local {
			return ""
		}
	}
	return s
}

// coveredBy: the entry of list that takes name (the name itself or a parent domain), or "".
func coveredBy(name string, list map[string]bool) string {
	for n := name; ; {
		if list[n] {
			return n
		}
		i := strings.IndexByte(n, '.')
		if i < 0 {
			return ""
		}
		n = n[i+1:]
		if !strings.Contains(n, ".") {
			return ""
		}
	}
}

// routerOwn: the router's own services - KeenDNS names (remote access to the router, its SSTP
// server through the cloud), Keenetic's cloud and updates, under both brands (owner 12.11.2026:
// remote access did not always connect). Never through the VPN: the cloud reaches the router on
// the provider's address.
func routerOwn(name string) bool {
	for _, z := range []string{"keenetic.pro", "keenetic.link", "keenetic.name", "keenetic.io", "keenetic.net", "keenetic.com",
		"netcraze.pro", "netcraze.link", "netcraze.name", "netcraze.io", "netcraze.net", "netcraze.com"} {
		if name == z || strings.HasSuffix(name, "."+z) {
			return true
		}
	}
	return false
}

// ruZone: names the owner keeps on the provider (ROADMAP: «.ru не в Автоподбор»; the shell
// engine's ru_zone): .ru, .рф, .su and the Russian services that answer the same either way.
func ruZone(name string) bool {
	for _, z := range []string{"ru", "xn--p1ai", "su", "yandex.net", "yandex.com", "yastatic.net",
		"vk.com", "vk.me", "userapi.com", "mycdn.me", "avito.st"} {
		if name == z || strings.HasSuffix(name, "."+z) {
			return true
		}
	}
	return false
}

// suffixOf: the entry of list that is name or a parent domain of it, or "".
func suffixOf(name string, list []string) string {
	for _, z := range list {
		if name == z || strings.HasSuffix(name, "."+z) {
			return z
		}
	}
	return ""
}

// sharedCDN: the common names of the content networks. Keenetic routes a name of the group by
// the addresses it resolves to, and behind these names the addresses belong to thousands of
// sites: one such name in the group takes other sites' traffic into the VPN too (owner's journal
// 12.11.2026: *.akamai.net, *.sni.global.fastly.net). The name is only marked for the Panel.
var sharedCDN = []string{"akamai.net", "akamaiedge.net", "akamaized.net", "akamaihd.net", "akamaitechnologies.com",
	"edgekey.net", "edgesuite.net", "fastly.net", "fastlylb.net", "cloudfront.net", "cdn.cloudflare.net",
	"azureedge.net", "azurefd.net", "trafficmanager.net", "llnwd.net", "cdn77.org", "b-cdn.net", "gcdn.co",
	"edgecastcdn.net", "footprint.net", "hwcdn.net", "kxcdn.com", "cdngslb.com"}

// SharedCDN: name is a content network's common name (the entry, or "").
func SharedCDN(name string) string { return suffixOf(name, sharedCDN) }

//go:embed ads.txt
var adsText string

var adNames = func() []string {
	var out []string
	for _, l := range strings.Split(adsText, "\n") {
		if l = strings.TrimSpace(l); l != "" && l[0] != '#' {
			out = append(out, l)
		}
	}
	return out
}()

// AdName: name is an advert, a counter or telemetry (the list's entry, or ""): ads.txt.
func AdName(name string) string { return suffixOf(name, adNames) }
