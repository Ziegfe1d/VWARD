package ndm

import (
	"fmt"
	"sort"
	"strings"
)

// Clone: a deep copy.
func (m *Model) Clone() *Model {
	c := newModel()
	for k, v := range m.Read {
		c.Read[k] = v
	}
	c.GroupOrder = append([]string(nil), m.GroupOrder...)
	for k, g := range m.Groups {
		cg := *g
		cg.Include = append([]string(nil), g.Include...)
		cg.Exclude = append([]string(nil), g.Exclude...)
		cg.Other = append([]string(nil), g.Other...)
		cg.Lines = append([]string(nil), g.Lines...)
		c.Groups[k] = &cg
	}
	c.Routes = append([]Route(nil), m.Routes...)
	c.DoH = append([]DoH(nil), m.DoH...)
	c.NameServers = append([]NameServer(nil), m.NameServers...)
	c.IPRoutes = append([]IPRoute(nil), m.IPRoutes...)
	c.Interfaces = append([]string(nil), m.Interfaces...)
	return c
}

// Apply one command of the routing core's set to the model: the expected image after a
// batch, written into the journal BEFORE the batch is sent.
func (m *Model) Apply(cmd string) error {
	no := strings.HasPrefix(cmd, "no ")
	f := strings.Fields(strings.TrimPrefix(cmd, "no "))
	// Keenetic's dns-proxy form: «dns-proxy no route ...», «dns-proxy no https ...».
	if len(f) >= 2 && f[0] == "dns-proxy" && f[1] == "no" {
		no, f = true, append([]string{"dns-proxy"}, f[2:]...)
	}
	switch {
	case len(f) >= 3 && f[0] == "object-group" && f[1] == "fqdn":
		name := f[2]
		g := m.Groups[name]
		if len(f) == 3 {
			if no {
				delete(m.Groups, name)
				m.GroupOrder = without(m.GroupOrder, name)
				var keep []Route
				for _, r := range m.Routes {
					if r.Group != name {
						keep = append(keep, r)
					}
				}
				m.Routes = keep
			} else if g == nil {
				m.Groups[name] = &Group{Name: name}
				m.GroupOrder = append(m.GroupOrder, name)
			}
			return nil
		}
		if g == nil {
			if no {
				return nil
			}
			g = &Group{Name: name}
			m.Groups[name] = g
			m.GroupOrder = append(m.GroupOrder, name)
		}
		switch {
		case f[3] == "include" && len(f) == 5:
			d := strings.ToLower(f[4])
			if no {
				g.Include = without(g.Include, d)
				g.Lines = without(g.Lines, "include "+d)
			} else if !contains(g.Include, d) {
				g.Include = append(g.Include, d)
				g.Lines = append(g.Lines, "include "+d)
			}
		case f[3] == "exclude" && len(f) == 5:
			d := strings.ToLower(f[4])
			if no {
				g.Exclude = without(g.Exclude, d)
				g.Lines = without(g.Lines, "exclude "+d)
			} else if !contains(g.Exclude, d) {
				g.Exclude = append(g.Exclude, d)
				g.Lines = append(g.Lines, "exclude "+d)
			}
		case f[3] == "description":
			var keep []string
			for _, l := range g.Lines {
				if !strings.HasPrefix(l, "description") {
					keep = append(keep, l)
				}
			}
			g.Lines, g.Description = keep, ""
			if !no {
				d := strings.TrimSpace(strings.SplitN(strings.TrimPrefix(cmd, "object-group fqdn "+name), "description", 2)[1])
				g.Description = d
				g.Lines = append(g.Lines, "description "+d)
			}
		default:
			return fmt.Errorf("apply: unsupported %q", cmd)
		}
	case len(f) >= 5 && f[0] == "dns-proxy" && f[1] == "route" && f[2] == "object-group":
		r := Route{Group: f[3], Target: f[4], Options: strings.Join(f[5:], " ")}
		var keep []Route
		found := false
		for _, x := range m.Routes {
			same := x.Group == r.Group && x.Target == r.Target
			if same && no {
				continue
			}
			if same && x.Options == r.Options {
				found = true
			}
			keep = append(keep, x)
		}
		if !no && !found {
			keep = append(keep, r)
		}
		m.Routes = keep
	case len(f) >= 4 && f[0] == "dns-proxy" && f[1] == "https" && f[2] == "upstream":
		raw := strings.Join(f[1:], " ")
		var keep []DoH
		found := false
		for _, x := range m.DoH {
			if x.Raw == raw {
				if no {
					continue
				}
				found = true
			}
			keep = append(keep, x)
		}
		if !no && !found {
			keep = append(keep, parseDoH(raw))
		}
		m.DoH = keep
	case len(f) == 3 && f[0] == "system" && f[1] == "configuration" && f[2] == "save":
	default:
		return fmt.Errorf("apply: unsupported %q", cmd)
	}
	return nil
}

func without(a []string, x string) []string {
	var out []string
	for _, y := range a {
		if y != x {
			out = append(out, y)
		}
	}
	return out
}

func contains(a []string, x string) bool {
	for _, y := range a {
		if y == x {
			return true
		}
	}
	return false
}

// Fingerprint of one area ("group:NAME", "route:NAME", "doh"): a canonical text; equal
// text = equal configuration of that area. An absent group is "absent".
func (m *Model) Fingerprint(area string) string {
	kind, name, _ := strings.Cut(area, ":")
	switch kind {
	case "group":
		g, ok := m.Groups[name]
		if !ok {
			return "absent"
		}
		lines := append([]string(nil), g.Lines...)
		for i := range lines {
			lines[i] = canonicalDescription(lines[i])
		}
		sort.Strings(lines)
		return strings.Join(lines, "\n")
	case "route":
		var out []string
		for _, r := range m.RoutesOf(name) {
			out = append(out, r.Target+" "+r.Options)
		}
		return strings.Join(out, "\n")
	case "doh":
		var out []string
		for _, r := range m.DoH {
			out = append(out, r.Raw)
		}
		sort.Strings(out)
		return strings.Join(out, "\n")
	}
	return "?" + area
}
