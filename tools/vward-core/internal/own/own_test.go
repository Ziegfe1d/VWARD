package own

import (
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/ndm"
)

var helper = func() string {
	b, err := os.ReadFile("../../../../components/console/scripts/vward-console-config.sh")
	if err != nil {
		panic(err)
	}
	return string(b)
}()

func shellFn(t *testing.T, name string) string {
	re := regexp.MustCompile(`(?ms)^` + regexp.QuoteMeta(name) + `\(\) \{\n.*?^\}\n`)
	m := re.FindString(helper)
	if m == "" {
		t.Fatalf("shell function %s not found", name)
	}
	return m
}

const running = `object-group fqdn domain-list7
    description "YouTube"
    include youtube.com
    include googlevideo.com
!
object-group fqdn domain-list8
    description Telegram
    include t.me
!
object-group fqdn domain-list9
    include changed.example
!
dns-proxy
    route object-group domain-list7 OpkgTun4 auto
    route object-group domain-list9 OpkgTun4 auto
!
`

type fixture struct {
	dir  string
	p    Paths
	m    *ndm.Model
	runf string
}

func setup(t *testing.T) *fixture {
	d := t.TempDir()
	f := &fixture{dir: d, p: Paths{Etc: filepath.Join(d, "etc"), Backup: filepath.Join(d, "backup")}, m: ndm.ParseRunning(running)}
	os.MkdirAll(filepath.Join(f.p.Etc, "services"), 0o755)
	os.MkdirAll(filepath.Join(f.p.Etc, "route-engine/domain-lists"), 0o755)
	os.MkdirAll(filepath.Join(f.p.Backup, "service-transactions.resolved"), 0o700)
	f.runf = filepath.Join(d, "running")
	os.WriteFile(f.runf, []byte(running), 0o600)
	return f
}

// txn writes one resolved service transaction: the service id created group g with this body.
func (f *fixture) txn(t *testing.T, name, id, g, state string, body []string, before string) {
	d := filepath.Join(f.p.Backup, "service-transactions.resolved", name)
	os.MkdirAll(d, 0o700)
	os.Chmod(d, 0o700)
	w := func(n, s string) { os.WriteFile(filepath.Join(d, n), []byte(s), 0o600) }
	w("after.enabled", id+"\t"+g+"\tauto\n")
	w("resolved", "state="+state+"\n")
	w("groups", g+"\n")
	w("new."+g, strings.Join(body, "\n")+"\n")
	w("group."+g, before)
	w("route."+g, "")
}

func (f *fixture) shell(t *testing.T, sh []string, id, target string) string {
	fns := ""
	for _, n := range []string{"valid_group", "group_routes", "service_canonical", "service_signature_raw", "service_signature", "service_origin"} {
		fns += shellFn(t, n)
	}
	script := "ADAPTIVE_GROUP=AdaptiveAuto; " + fns + `service_origin "$1" "$2"`
	cmd := exec.Command(sh[0], append(sh[1:], "-c", script, "origin", id, target)...)
	cmd.Env = append(os.Environ(), "LC_ALL=C", "BACKUP_DIR="+f.p.Backup, "SERVICES_STATE="+filepath.Join(f.p.Etc, "services/enabled.tsv"),
		"LISTS_STATE="+filepath.Join(f.p.Etc, "route-engine/domain-lists"), "VWARD_TUNNEL_INTERFACE=OpkgTun4", "RUNCFG="+f.runf)
	out, _ := cmd.Output()
	return strings.TrimSpace(string(out))
}

func shells() [][]string {
	var out [][]string
	if p, err := exec.LookPath("sh"); err == nil {
		out = append(out, []string{p})
	}
	if p, err := exec.LookPath("busybox"); err == nil {
		out = append(out, []string{p, "ash"})
	}
	return out
}

func TestOriginParity(t *testing.T) {
	yt := []string{`description "YouTube"`, "include youtube.com", "include googlevideo.com"}
	cases := []struct {
		name    string
		prepare func(f *fixture)
		id      string
		want    string
	}{
		{"created and unchanged", func(f *fixture) { f.txn(t, "txn.aaaaaa", "youtube", "domain-list7", "committed", yt, "") }, "youtube", "domain-list7"},
		{"partial accepted", func(f *fixture) { f.txn(t, "txn.aaaaaa", "youtube", "domain-list7", "accepted:partial", yt, "") }, "youtube", "domain-list7"},
		{"not accepted", func(f *fixture) { f.txn(t, "txn.aaaaaa", "youtube", "domain-list7", "pending", yt, "") }, "youtube", ""},
		{"existed before (adopted a list)", func(f *fixture) { f.txn(t, "txn.aaaaaa", "youtube", "domain-list7", "committed", yt, "include x\n") }, "youtube", ""},
		{"changed since", func(f *fixture) {
			f.txn(t, "txn.aaaaaa", "changed", "domain-list9", "committed", []string{"include original.example"}, "")
		}, "changed", ""},
		{"other service", func(f *fixture) { f.txn(t, "txn.aaaaaa", "youtube", "domain-list7", "committed", yt, "") }, "telegram", ""},
		{"two groups for one service", func(f *fixture) {
			f.txn(t, "txn.aaaaaa", "youtube", "domain-list7", "committed", yt, "")
			f.txn(t, "txn.bbbbbb", "youtube", "domain-list8", "committed", []string{"description Telegram", "include t.me"}, "")
		}, "youtube", ""},
		{"loose directory mode", func(f *fixture) {
			f.txn(t, "txn.aaaaaa", "youtube", "domain-list7", "committed", yt, "")
			os.Chmod(filepath.Join(f.p.Backup, "service-transactions.resolved", "txn.aaaaaa"), 0o755)
		}, "youtube", ""},
		{"listed in enabled.tsv (shell reconnects only absent ones)", func(f *fixture) {
			f.txn(t, "txn.aaaaaa", "youtube", "domain-list7", "committed", yt, "")
			os.WriteFile(filepath.Join(f.p.Etc, "services/enabled.tsv"), []byte("youtube\tdomain-list7\tauto\n"), 0o644)
		}, "youtube", ""},
	}
	sh := shells()
	if len(sh) == 0 {
		t.Skip("no shell")
	}
	for _, c := range cases {
		f := setup(t)
		c.prepare(f)
		skip := map[string]bool{}
		if b, err := os.ReadFile(filepath.Join(f.p.Etc, "services/enabled.tsv")); err == nil {
			for _, l := range strings.Split(string(b), "\n") {
				if p := strings.Split(l, "\t"); len(p) == 3 {
					skip[p[1]] = true
				}
			}
		}
		got := Origin(f.p, f.m, c.id, "vpn", "OpkgTun4", skip)
		for _, s := range sh {
			if want := f.shell(t, s, c.id, "vpn"); want != got || got != c.want {
				t.Fatalf("%s (%v): shell %q, go %q, expected %q", c.name, s, want, got, c.want)
			}
		}
	}
}

func TestServiceVerdicts(t *testing.T) {
	f := setup(t)
	yt := []string{`description "YouTube"`, "include youtube.com", "include googlevideo.com"}
	f.txn(t, "txn.aaaaaa", "youtube", "domain-list7", "committed", yt, "")
	// Enabled now: as ownership evidence the journal still counts (not the reconnect rule).
	if v := Service(f.p, f.m, "youtube", "domain-list7", "auto", "OpkgTun4"); v.Level != Full || v.Reason != "provenance" {
		t.Fatalf("provenance: %+v", v)
	}
	// A claim file equal to the group now.
	os.MkdirAll(filepath.Join(f.p.Etc, "services/owned"), 0o700)
	sig, _ := f.m.Signature("domain-list8")
	os.WriteFile(filepath.Join(f.p.Etc, "services/owned/domain-list8"), []byte(sig), 0o600)
	if v := Service(f.p, f.m, "telegram", "domain-list8", "OpkgTun4", "OpkgTun4"); v.Level != Full || v.Reason != "claim" {
		t.Fatalf("claim: %+v", v)
	}
	// The owner edited a claimed group: the claim does not match, the journal does not override it.
	os.WriteFile(filepath.Join(f.p.Etc, "services/owned/domain-list7"), []byte("include other.example\n"), 0o600)
	if v := Service(f.p, f.m, "youtube", "domain-list7", "auto", "OpkgTun4"); v.Level != None || v.Reason != "changed-since-claim" {
		t.Fatalf("edited claim: %+v", v)
	}
	os.Remove(filepath.Join(f.p.Etc, "services/owned/domain-list7"))
	// A claim readable by others is no proof.
	os.Chmod(filepath.Join(f.p.Etc, "services/owned/domain-list8"), 0o644)
	if v := Service(f.p, f.m, "telegram", "domain-list8", "OpkgTun4", "OpkgTun4"); v.Level != None || v.Reason != "proof-mode" {
		t.Fatalf("loose claim: %+v", v)
	}
	// The owner's «list-adopt»: the route only.
	os.WriteFile(filepath.Join(f.p.Etc, "route-engine/domain-lists.conf"), []byte("managed.domain-list9=1\n"), 0o644)
	if v := Service(f.p, f.m, "x", "domain-list9", "auto", "OpkgTun4"); v.Level != Route || v.Reason != "adopted" {
		t.Fatalf("adopted: %+v", v)
	}
	// Nothing: foreign. AdaptiveAuto is never a service group.
	if v := Service(f.p, f.m, "y", "domain-list0", "auto", "OpkgTun4"); v.Level != None || v.Reason != "no-proof" {
		t.Fatalf("no proof: %+v", v)
	}
	if v := Service(f.p, f.m, "y", "AdaptiveAuto", "auto", "OpkgTun4"); v.Level != None {
		t.Fatalf("adaptive: %+v", v)
	}
}
