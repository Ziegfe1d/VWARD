package main

import "strings"

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

// Second-level suffixes under which sites are registered one level deeper.
var multiSuffix = map[string]bool{
	"com.ru": true, "net.ru": true, "org.ru": true, "pp.ru": true, "msk.ru": true, "spb.ru": true,
	"com.ua": true, "org.ua": true, "net.ua": true, "co.uk": true, "org.uk": true, "ac.uk": true,
	"com.tr": true, "co.jp": true, "ne.jp": true, "com.br": true, "com.au": true, "com.cn": true,
	"co.kr": true, "co.in": true, "com.kz": true, "org.kz": true, "co.il": true, "com.sg": true,
	"github.io": true, "appspot.com": true, "herokuapp.com": true, "pages.dev": true, "workers.dev": true,
	"vercel.app": true, "netlify.app": true, "blogspot.com": true, "cloudfront.net": true,
	"azurewebsites.net": true, "web.app": true, "firebaseapp.com": true,
}

// baseDomain: the registered domain of name (example.com for a.b.example.com).
func baseDomain(name string) string {
	l := strings.Split(name, ".")
	if len(l) <= 2 {
		return name
	}
	two := l[len(l)-2] + "." + l[len(l)-1]
	if multiSuffix[two] {
		return strings.Join(l[len(l)-3:], ".")
	}
	return two
}
