package adaptive

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
