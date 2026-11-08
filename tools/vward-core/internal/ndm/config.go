// Package ndm models the parts of a Keenetic configuration the routing core reads and
// writes: FQDN groups, their dns-proxy routes, Smart DNS (DoH) rows, per-domain name
// servers and static IP routes. The same model is built from the full running-config
// text (first start, recovery) and from narrow RCI answers (every request); the dry-run
// proves on the router that both give the same model before any writer relies on it.
package ndm

import (
	"bufio"
	"sort"
	"strings"
)

// Group is one «object-group fqdn NAME».
type Group struct {
	Name        string
	Description string
	Include     []string // in configuration order, lower case
	Exclude     []string
	Other       []string // any other line of the group, kept verbatim (never dropped)
	Lines       []string // every non-empty line without indentation, as printed (signature)
}

// Route is one «dns-proxy route object-group GROUP TARGET [OPTIONS]».
type Route struct {
	Group   string
	Target  string
	Options string // "auto", "" ...
}

// DoH is one «dns-proxy https upstream URL ...» row (Smart DNS).
type DoH struct {
	Raw    string // the row without indentation, exactly as Keenetic prints it
	URL    string
	Iface  string // after «on», "" when none
	Domain string // after «domain», "" when none
}

// NameServer is one «ip name-server ADDR[:PORT] [DOMAIN] [on IFACE]».
type NameServer struct {
	Raw    string
	Addr   string
	Domain string
	Iface  string
}

// IPRoute is one «ip route NET MASK TARGET [OPTIONS]».
type IPRoute struct {
	Raw     string
	Net     string
	Mask    string
	Target  string
	Options string
}

// Model is what the core knows of the router. Areas a narrow read did not fetch are nil
// (unknown), never empty: an empty slice means «read, and there is none».
type Model struct {
	Groups      map[string]*Group
	GroupOrder  []string
	Routes      []Route
	DoH         []DoH
	NameServers []NameServer
	IPRoutes    []IPRoute
	Interfaces  []string
	Read        map[string]bool // area -> was read (groups, routes, doh, nameservers, iproutes, interfaces)
}

func newModel() *Model {
	return &Model{Groups: map[string]*Group{}, Read: map[string]bool{}}
}

func fields(s string) []string { return strings.Fields(s) }

// ParseRunning builds the model from «show running-config» text. Every area is marked read.
func ParseRunning(text string) *Model {
	m := newModel()
	for _, a := range []string{"groups", "routes", "doh", "nameservers", "iproutes", "interfaces"} {
		m.Read[a] = true
	}
	m.Routes, m.DoH, m.NameServers, m.IPRoutes, m.Interfaces = []Route{}, []DoH{}, []NameServer{}, []IPRoute{}, []string{}
	sc := bufio.NewScanner(strings.NewReader(text))
	sc.Buffer(make([]byte, 64*1024), 4*1024*1024)
	ctx := ""
	var cur *Group
	for sc.Scan() {
		line := strings.TrimRight(sc.Text(), "\r")
		if line == "" {
			continue
		}
		if strings.HasPrefix(line, "!") {
			ctx, cur = "", nil
			continue
		}
		top := line[0] != ' ' && line[0] != '\t'
		f := fields(line)
		if len(f) == 0 {
			continue
		}
		if top {
			ctx, cur = "", nil
			switch {
			case len(f) == 3 && f[0] == "object-group" && f[1] == "fqdn":
				cur = &Group{Name: f[2]}
				if _, dup := m.Groups[f[2]]; !dup {
					m.GroupOrder = append(m.GroupOrder, f[2])
				}
				m.Groups[f[2]] = cur
				ctx = "group"
			case len(f) == 1 && f[0] == "dns-proxy":
				ctx = "dns-proxy"
			case len(f) >= 2 && f[0] == "interface":
				m.Interfaces = append(m.Interfaces, f[1])
			case len(f) >= 3 && f[0] == "ip" && f[1] == "name-server":
				m.NameServers = append(m.NameServers, parseNameServer(line))
			case len(f) >= 5 && f[0] == "ip" && f[1] == "route":
				m.IPRoutes = append(m.IPRoutes, IPRoute{Raw: line, Net: f[2], Mask: f[3], Target: f[4], Options: strings.Join(f[5:], " ")})
			}
			continue
		}
		body := strings.TrimLeft(line, " \t")
		switch ctx {
		case "group":
			cur.Lines = append(cur.Lines, body)
			switch {
			case f[0] == "include" && len(f) == 2:
				cur.Include = append(cur.Include, strings.ToLower(f[1]))
			case f[0] == "exclude" && len(f) == 2:
				cur.Exclude = append(cur.Exclude, strings.ToLower(f[1]))
			case f[0] == "description":
				cur.Description = strings.TrimSpace(strings.TrimPrefix(body, "description"))
			default:
				cur.Other = append(cur.Other, body)
			}
		case "dns-proxy":
			switch {
			case len(f) >= 4 && f[0] == "route" && f[1] == "object-group":
				m.Routes = append(m.Routes, Route{Group: f[2], Target: f[3], Options: strings.Join(f[4:], " ")})
			case len(f) >= 3 && f[0] == "https" && f[1] == "upstream":
				m.DoH = append(m.DoH, parseDoH(body))
			}
		}
	}
	return m
}

func parseDoH(raw string) DoH {
	f := fields(raw)
	d := DoH{Raw: raw}
	if len(f) >= 3 {
		d.URL = f[2]
	}
	for i := 3; i+1 < len(f); i++ {
		switch f[i] {
		case "on":
			d.Iface = f[i+1]
		case "domain":
			d.Domain = strings.ToLower(f[i+1])
		}
	}
	return d
}

func parseNameServer(raw string) NameServer {
	f := fields(raw)
	ns := NameServer{Raw: raw}
	if len(f) >= 3 {
		ns.Addr = f[2]
	}
	rest := f[3:]
	for i := 0; i < len(rest); i++ {
		if rest[i] == "on" && i+1 < len(rest) {
			ns.Iface = rest[i+1]
			i++
			continue
		}
		if ns.Domain == "" {
			ns.Domain = strings.ToLower(rest[i])
		}
	}
	return ns
}

// RoutesOf: the dns-proxy routes of one group, sorted.
func (m *Model) RoutesOf(g string) []Route {
	var out []Route
	for _, r := range m.Routes {
		if r.Group == g {
			out = append(out, r)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Target+"\t"+out[i].Options < out[j].Target+"\t"+out[j].Options })
	return out
}

// Signature is the ownership proof of a group, byte for byte the form
// vward-console-config.sh service_signature writes into services/owned/GROUP: every
// non-empty line of the group without indentation, plus «route=TARGET<TAB>OPTIONS»
// per dns-proxy route, sorted; a complete simple quoted description is unquoted.
func (m *Model) Signature(g string) (string, bool) {
	grp, ok := m.Groups[g]
	if !ok {
		return "", false
	}
	var lines []string
	for _, l := range grp.Lines {
		lines = append(lines, canonicalDescription(l))
	}
	for _, r := range m.RoutesOf(g) {
		o := r.Options
		if o == "" {
			o = "-"
		}
		lines = append(lines, "route="+r.Target+"\t"+o)
	}
	sort.Strings(lines)
	return strings.Join(lines, "\n") + "\n", true
}

// CanonicalSignature normalises a stored signature the same way (service_canonical).
func CanonicalSignature(s string) string {
	var lines []string
	for _, l := range strings.Split(strings.TrimRight(s, "\n"), "\n") {
		lines = append(lines, canonicalDescription(l))
	}
	sort.Strings(lines)
	return strings.Join(lines, "\n") + "\n"
}

func canonicalDescription(l string) string {
	if strings.HasPrefix(l, `description "`) && strings.HasSuffix(l, `"`) && len(l) >= 14 {
		d := l[13 : len(l)-1]
		if !strings.ContainsAny(d, `"\`) {
			return "description " + d
		}
	}
	return l
}
