package ndm

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
)

// RunningFromRCI: «show running-config» through RCI answers {"message": ["line", ...]}
// (or a bare array of lines, or plain text). Lines are returned as running-config text.
func RunningFromRCI(b []byte) (string, error) {
	var obj struct {
		Message []string `json:"message"`
	}
	if json.Unmarshal(b, &obj) == nil && len(obj.Message) > 0 {
		return strings.Join(obj.Message, "\n") + "\n", nil
	}
	var arr []string
	if json.Unmarshal(b, &arr) == nil && len(arr) > 0 {
		return strings.Join(arr, "\n") + "\n", nil
	}
	if len(b) > 0 && b[0] != '{' && b[0] != '[' {
		return string(b), nil
	}
	return "", fmt.Errorf("running-config: unknown answer shape")
}

// GroupsFromRCI: GET /rci/object-group/fqdn, the configuration subtree of FQDN groups.
// Accepted shapes (KeeneticOS answers objects keyed by name; a list form is accepted too):
//
//	{"NAME": {"include": [{"address": "a.com"}, ...], "exclude": [...], "description": "..."}}
//	{"fqdn": {...}}            [{"name": "NAME", "include": [...]}]
func GroupsFromRCI(b []byte, m *Model) error {
	var v any
	if err := json.Unmarshal(b, &v); err != nil {
		return err
	}
	if o, ok := v.(map[string]any); ok {
		if inner, ok := o["fqdn"].(map[string]any); ok && len(o) == 1 {
			v = inner
		}
	}
	add := func(name string, body map[string]any) {
		g := &Group{Name: name}
		if d, ok := body["description"].(string); ok && d != "" {
			g.Description = d
			if strings.ContainsAny(d, " \t") {
				g.Description = `"` + d + `"`
			}
			g.Lines = append(g.Lines, "description "+g.Description)
		}
		for _, kind := range []string{"include", "exclude"} {
			for _, x := range list(body[kind]) {
				d := strings.ToLower(addr(x))
				if d == "" {
					continue
				}
				if kind == "include" {
					g.Include = append(g.Include, d)
				} else {
					g.Exclude = append(g.Exclude, d)
				}
				g.Lines = append(g.Lines, kind+" "+d)
			}
		}
		m.Groups[name] = g
		m.GroupOrder = append(m.GroupOrder, name)
	}
	switch t := v.(type) {
	case map[string]any:
		names := make([]string, 0, len(t))
		for k := range t {
			names = append(names, k)
		}
		sort.Strings(names)
		for _, k := range names {
			body, _ := t[k].(map[string]any)
			if body == nil {
				body = map[string]any{}
			}
			add(k, body)
		}
	case []any:
		for _, x := range t {
			body, _ := x.(map[string]any)
			name, _ := body["name"].(string)
			if name == "" {
				return fmt.Errorf("fqdn groups: element without name")
			}
			add(name, body)
		}
	default:
		return fmt.Errorf("fqdn groups: unknown answer shape")
	}
	m.Read["groups"] = true
	return nil
}

// DNSProxyFromRCI: GET /rci/dns-proxy, the dns-proxy subtree: its routes and Smart DNS rows.
//
//	{"route": [{"object-group": "G", "interface": "T", "auto": true}, ...],
//	 "https": {"upstream": [{"url": "...", "format": "dnsm", "on": "ISP", "domain": "x"}]}}
func DNSProxyFromRCI(b []byte, m *Model) error {
	var o map[string]any
	if err := json.Unmarshal(b, &o); err != nil {
		return err
	}
	m.Routes, m.DoH = []Route{}, []DoH{}
	for _, x := range list(o["route"]) {
		r, _ := x.(map[string]any)
		g := str(r, "object-group", "group", "name")
		t := str(r, "interface", "target", "gateway")
		if g == "" || t == "" {
			return fmt.Errorf("dns-proxy route: unknown element shape")
		}
		opts := ""
		if b, ok := r["auto"].(bool); ok && b {
			opts = "auto"
		}
		if r["reject"] == true {
			opts = strings.TrimSpace(opts + " reject")
		}
		m.Routes = append(m.Routes, Route{Group: g, Target: t, Options: opts})
	}
	var ups []any
	if h, ok := o["https"].(map[string]any); ok {
		ups = list(h["upstream"])
	}
	for _, x := range ups {
		u, _ := x.(map[string]any)
		url := str(u, "url", "address")
		if url == "" {
			return fmt.Errorf("dns-proxy https: unknown element shape")
		}
		raw := "https upstream " + url
		if f := str(u, "format"); f != "" {
			raw += " " + f
		}
		if on := str(u, "on", "interface"); on != "" {
			raw += " on " + on
		}
		if d := str(u, "domain"); d != "" {
			raw += " domain " + d
		}
		m.DoH = append(m.DoH, parseDoH(raw))
	}
	m.Read["routes"], m.Read["doh"] = true, true
	return nil
}

func list(v any) []any {
	switch t := v.(type) {
	case []any:
		return t
	case nil:
		return nil
	default:
		return []any{t}
	}
}

func addr(x any) string {
	switch t := x.(type) {
	case string:
		return t
	case map[string]any:
		return str(t, "address", "fqdn", "name", "domain")
	}
	return ""
}

func str(o map[string]any, keys ...string) string {
	for _, k := range keys {
		if s, ok := o[k].(string); ok {
			return s
		}
	}
	return ""
}

// Shape: the structure of a JSON answer without its values (dry-run report: what this
// firmware answers, so a parser can be fixed without sending anyone's data).
func Shape(b []byte, depth int) string {
	var v any
	if json.Unmarshal(b, &v) != nil {
		if len(b) > 40 {
			b = b[:40]
		}
		return fmt.Sprintf("not JSON (%q...)", string(b))
	}
	return shape(v, depth)
}

func shape(v any, depth int) string {
	switch t := v.(type) {
	case map[string]any:
		if depth == 0 {
			return fmt.Sprintf("{%d keys}", len(t))
		}
		keys := make([]string, 0, len(t))
		for k := range t {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		if len(keys) > 6 {
			// Named entries (groups): one sample, keys not shown.
			return fmt.Sprintf("{%d keys, e.g. <name>: %s}", len(keys), shape(t[keys[0]], depth-1))
		}
		var parts []string
		for _, k := range keys {
			parts = append(parts, k+": "+shape(t[k], depth-1))
		}
		return "{" + strings.Join(parts, ", ") + "}"
	case []any:
		if len(t) == 0 {
			return "[]"
		}
		return fmt.Sprintf("[%d x %s]", len(t), shape(t[0], depth-1))
	case string:
		return "str"
	case bool:
		return "bool"
	case float64:
		return "num"
	case nil:
		return "null"
	}
	return "?"
}
