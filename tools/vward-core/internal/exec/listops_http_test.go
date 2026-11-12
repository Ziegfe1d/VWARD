package exec_test

import (
	"path/filepath"
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
