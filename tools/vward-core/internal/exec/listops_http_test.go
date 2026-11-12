package exec_test

import (
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/exec"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/journal"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/listops"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/rci"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/router"
)

// The Panel's list operations over real HTTP RCI: only the asked change, the owner's other
// lists, the 8 Google subnets, the 16 name-server rules and the NextDNS row byte for byte.
func TestListOpsOverRCI(t *testing.T) {
	k := exec.NewFakeKeenetic(t, exec.OwnerCfg)
	before := k.Running()
	r := router.New(rci.New(k.Addr(), false), true)
	j := &journal.Journal{Dir: filepath.Join(t.TempDir(), "j")}
	res, err := listops.Run(r, j, listops.Op{Kind: "add", Group: "domain-list0", Domain: "telegram.me"}, time.Unix(1, 0))
	if err != nil || res.State != "changed" {
		t.Fatalf("add: %v %+v", err, res)
	}
	want := strings.Replace(before, "    include telegram.org\n", "    include telegram.org\n    include telegram.me\n", 1)
	if k.Running() != want {
		t.Fatalf("beyond the one name:\n%s", k.Running())
	}
	res, err = listops.Run(r, j, listops.Op{Kind: "route", Group: "domain-list4", Target: "Wireguard1", Options: "auto"}, time.Unix(2, 0))
	if err != nil || res.State != "changed" {
		t.Fatalf("route: %v %+v", err, res)
	}
	after := k.Running()
	if !strings.Contains(after, "route object-group domain-list4 Wireguard1 auto") || strings.Contains(after, "route object-group domain-list4 OpkgTun4") {
		t.Fatalf("route not moved:\n%s", after)
	}
	for _, keep := range []string{"route object-group domain-list0 OpkgTun4 auto", "route object-group AdaptiveAuto OpkgTun4 auto", "nextdns", "ip route 8.8.8.0 255.255.255.0 OpkgTun4 auto", "ip name-server 1.1.1.1 yt3.ggpht.com on OpkgTun4"} {
		if !strings.Contains(after, keep) {
			t.Fatalf("%q lost", keep)
		}
	}
	if res, _ := listops.Run(r, j, listops.Op{Kind: "delete", Group: "AdaptiveAuto"}, time.Unix(3, 0)); res.State != "refused" {
		t.Fatalf("AdaptiveAuto is not a Panel list: %+v", res)
	}
}

// The default tunnel switched: the routes of several groups move in one batch; Keenetic
// refusing one command in the middle takes everything back (compensation), nothing half-moved.
func TestRetargetOverRCIAndCompensation(t *testing.T) {
	k := exec.NewFakeKeenetic(t, exec.OwnerCfg)
	before := k.Running()
	r := router.New(rci.New(k.Addr(), false), true)
	j := &journal.Journal{Dir: filepath.Join(t.TempDir(), "j")}
	op := listops.Op{Kind: "retarget", From: "OpkgTun4", Target: "Wireguard1", Groups: []string{"domain-list0", "domain-list4", "AdaptiveAuto"}}
	k.RefuseOn("no route object-group domain-list4 OpkgTun4")
	res, err := listops.Run(r, j, op, time.Unix(1, 0))
	if err != nil || res.State != "failed" {
		t.Fatalf("a refused step: %v %+v", err, res)
	}
	if lines(k.Running()) != lines(before) {
		t.Fatalf("not taken back:\n%s", k.Running())
	}
	k.RefuseOn("")
	res, err = listops.Run(r, j, op, time.Unix(2, 0))
	if err != nil || res.State != "changed" {
		t.Fatalf("retarget: %v %+v", err, res)
	}
	after := k.Running()
	for _, g := range []string{"domain-list0", "domain-list4", "AdaptiveAuto"} {
		if !strings.Contains(after, "route object-group "+g+" Wireguard1 auto") || strings.Contains(after, "route object-group "+g+" OpkgTun4") {
			t.Fatalf("%s not moved:\n%s", g, after)
		}
	}
	if !strings.Contains(after, "ip route 8.8.8.0 255.255.255.0 OpkgTun4 auto") {
		t.Fatal("a static route moved: the core never writes ip route")
	}
	// An exclusion through the real path, then taken out.
	if res, err := listops.Run(r, j, listops.Op{Kind: "exclude", Group: "domain-list0", Domain: "kids.t.me"}, time.Unix(3, 0)); err != nil || res.State != "changed" || !strings.Contains(k.Running(), "exclude kids.t.me") {
		t.Fatalf("exclude: %v %+v", err, res)
	}
}

// lines: the configuration as a set of lines (Keenetic may list a route put back last).
func lines(s string) string {
	l := strings.Split(s, "\n")
	sort.Strings(l)
	return strings.Join(l, "\n")
}
