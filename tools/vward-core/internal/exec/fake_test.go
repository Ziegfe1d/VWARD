package exec

import (
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"sort"
	"strings"
	"sync"
	"testing"
)

// fakeKeenetic: an RCI server with its own configuration state (independent of the ndm
// model the core uses), rendering running-config text and the narrow JSON answers.
type fakeKeenetic struct {
	mu       sync.Mutex
	groups   map[string][]string // name -> lines (include/exclude/description), in order
	order    []string
	routes   [][3]string // group, target, options
	doh      []string    // raw rows
	static   []string    // ip route / ip name-server lines, verbatim
	refuseAt int         // 1-based command index of a batch to refuse (0: none)
	refuseOn string      // refuse any command containing this
	dropAt   int         // close the connection without an answer after this many commands applied (-1: none)
	batches  [][]string
	reads    int
	fullRead int
	srv      *httptest.Server
}

func newFake(t *testing.T, cfg string) *fakeKeenetic {
	f := &fakeKeenetic{groups: map[string][]string{}, dropAt: -1}
	cur, dns := "", false
	for _, l := range strings.Split(cfg, "\n") {
		if strings.TrimSpace(l) == "" {
			continue
		}
		if strings.HasPrefix(l, "!") {
			cur, dns = "", false
			continue
		}
		fl := strings.Fields(l)
		if l[0] != ' ' {
			cur, dns = "", false
			switch {
			case fl[0] == "object-group":
				cur = fl[2]
				f.groups[cur] = nil
				f.order = append(f.order, cur)
			case fl[0] == "dns-proxy":
				dns = true
			default:
				f.static = append(f.static, l)
			}
			continue
		}
		body := strings.TrimSpace(l)
		if cur != "" {
			f.groups[cur] = append(f.groups[cur], body)
		} else if dns && fl[0] == "route" {
			f.routes = append(f.routes, [3]string{fl[2], fl[3], strings.Join(fl[4:], " ")})
		} else if dns && fl[0] == "https" {
			f.doh = append(f.doh, body)
		}
	}
	f.srv = httptest.NewServer(http.HandlerFunc(f.serve))
	t.Cleanup(f.srv.Close)
	return f
}

func (f *fakeKeenetic) addr() string { return strings.TrimPrefix(f.srv.URL, "http://") }

func (f *fakeKeenetic) running() string {
	var b strings.Builder
	for _, g := range f.order {
		b.WriteString("object-group fqdn " + g + "\n")
		for _, l := range f.groups[g] {
			b.WriteString("    " + l + "\n")
		}
		b.WriteString("!\n")
	}
	b.WriteString("dns-proxy\n")
	for _, r := range f.routes {
		b.WriteString(strings.TrimRight("    route object-group "+r[0]+" "+r[1]+" "+r[2], " ") + "\n")
	}
	for _, d := range f.doh {
		b.WriteString("    " + d + "\n")
	}
	b.WriteString("!\n")
	for _, s := range f.static {
		b.WriteString(s + "\n")
	}
	return b.String()
}

func (f *fakeKeenetic) serve(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	switch {
	case r.Method == "GET" && r.URL.Path == "/rci/show/running-config":
		f.fullRead++
		json.NewEncoder(w).Encode(map[string]any{"message": strings.Split(strings.TrimRight(f.running(), "\n"), "\n")})
	case r.Method == "GET" && r.URL.Path == "/rci/object-group/fqdn":
		f.reads++
		out := map[string]any{}
		for _, g := range f.order {
			body := map[string]any{}
			var inc, exc []any
			for _, l := range f.groups[g] {
				fl := strings.Fields(l)
				switch fl[0] {
				case "include":
					inc = append(inc, map[string]any{"address": fl[1]})
				case "exclude":
					exc = append(exc, map[string]any{"address": fl[1]})
				case "description":
					body["description"] = strings.Trim(strings.TrimPrefix(l, "description "), `"`)
				}
			}
			if inc != nil {
				body["include"] = inc
			}
			if exc != nil {
				body["exclude"] = exc
			}
			out[g] = body
		}
		json.NewEncoder(w).Encode(out)
	case r.Method == "GET" && r.URL.Path == "/rci/dns-proxy":
		f.reads++
		var rs, ups []any
		for _, x := range f.routes {
			rs = append(rs, map[string]any{"object-group": x[0], "interface": x[1], "auto": x[2] == "auto"})
		}
		for _, d := range f.doh {
			fl := strings.Fields(d)
			u := map[string]any{"url": fl[2], "format": fl[3]}
			for i := 4; i+1 < len(fl); i++ {
				if fl[i] == "on" {
					u["on"] = fl[i+1]
				}
				if fl[i] == "domain" {
					u["domain"] = fl[i+1]
				}
			}
			ups = append(ups, u)
		}
		json.NewEncoder(w).Encode(map[string]any{"route": rs, "https": map[string]any{"upstream": ups}})
	case r.Method == "POST" && r.URL.Path == "/rci/":
		body, _ := io.ReadAll(r.Body)
		var cmds []struct {
			Parse string `json:"parse"`
		}
		json.Unmarshal(body, &cmds)
		var batch []string
		var res []any
		for i, c := range cmds {
			batch = append(batch, c.Parse)
			if f.dropAt == i {
				f.batches = append(f.batches, batch)
				hj, _ := w.(http.Hijacker)
				conn, _, _ := hj.Hijack()
				conn.(*net.TCPConn).SetLinger(0)
				conn.Close()
				return
			}
			if (f.refuseAt == i+1) || (f.refuseOn != "" && strings.Contains(c.Parse, f.refuseOn)) {
				res = append(res, map[string]any{"status": []any{map[string]any{"status": "error", "message": "refused"}}})
				continue
			}
			f.apply(c.Parse)
			res = append(res, map[string]any{"parse": map[string]any{"status": []any{map[string]any{"status": "message"}}}})
		}
		f.batches = append(f.batches, batch)
		json.NewEncoder(w).Encode(res)
	default:
		http.NotFound(w, r)
	}
}

func (f *fakeKeenetic) apply(cmd string) {
	no := strings.HasPrefix(cmd, "no ")
	fl := strings.Fields(strings.TrimPrefix(cmd, "no "))
	if fl[0] == "dns-proxy" {
		fl2 := fl[1:]
		if len(fl2) > 0 && fl2[0] == "no" {
			no, fl2 = true, fl2[1:]
		}
		if fl2[0] == "route" {
			key := [3]string{fl2[2], fl2[3], strings.Join(fl2[4:], " ")}
			var keep [][3]string
			for _, x := range f.routes {
				if x[0] == key[0] && x[1] == key[1] && no {
					continue
				}
				keep = append(keep, x)
			}
			if !no {
				keep = append(keep, key)
			}
			f.routes = keep
		}
		if fl2[0] == "https" {
			raw := strings.Join(fl2, " ")
			var keep []string
			for _, d := range f.doh {
				if d != raw {
					keep = append(keep, d)
				}
			}
			if !no {
				keep = append(keep, raw)
			}
			f.doh = keep
		}
		return
	}
	if fl[0] == "object-group" {
		g := fl[2]
		if _, ok := f.groups[g]; !ok && !no {
			f.groups[g] = nil
			f.order = append(f.order, g)
		}
		if len(fl) == 3 {
			if no {
				delete(f.groups, g)
				var o []string
				for _, x := range f.order {
					if x != g {
						o = append(o, x)
					}
				}
				f.order = o
			}
			return
		}
		line := strings.Join(fl[3:], " ")
		// Keenetic drops the quotes of a simple description.
		if fl[3] == "description" {
			v := strings.TrimSpace(strings.TrimPrefix(line, "description"))
			if u := strings.Trim(v, `"`); !strings.ContainsAny(u, " \t\"") {
				line = "description " + u
			}
		}
		var keep []string
		for _, l := range f.groups[g] {
			if l == line || (fl[3] == "description" && strings.HasPrefix(l, "description")) {
				continue
			}
			keep = append(keep, l)
		}
		if !no {
			keep = append(keep, line)
		}
		if _, ok := f.groups[g]; ok {
			f.groups[g] = keep
		}
		return
	}
	if fl[0] == "system" {
		return
	}
	panic(fmt.Sprintf("fake: unsupported %q", cmd))
}

func (f *fakeKeenetic) staticLines() string {
	f.mu.Lock()
	defer f.mu.Unlock()
	s := append([]string(nil), f.static...)
	sort.Strings(s)
	return strings.Join(s, "\n")
}
