package exec_test

import (
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/exec"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/journal"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/rci"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/router"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/selftest"
)

// The router test through the real path: HTTP RCI, narrow JSON reads, one batch per step.
// The owner's configuration (lists, 8 Google subnets, 16 name-server rules, NextDNS row)
// is byte for byte the same afterwards.
func TestSelftestOverRCI(t *testing.T) {
	k := exec.NewFakeKeenetic(t, exec.OwnerCfg)
	before := k.Running()
	r := router.New(rci.New(k.Addr(), false), true)
	j := &journal.Journal{Dir: filepath.Join(t.TempDir(), "journal")}
	rep, err := selftest.Run(r, j, "OpkgTun4", time.Unix(1000, 0), true)
	if err != nil || !rep.OK {
		t.Fatalf("selftest over RCI: %v %+v", err, rep)
	}
	if after := k.Running(); after != before {
		t.Fatalf("the configuration differs after the test:\n--- before\n%s\n--- after\n%s", before, after)
	}
	var sent []string
	for _, b := range k.Batches() {
		for _, c := range b {
			if c != "system configuration save" {
				sent = append(sent, c)
			}
		}
	}
	for _, c := range sent {
		if !strings.Contains(c, selftest.Group) {
			t.Fatalf("a command outside the test group: %q", c)
		}
	}
	if len(sent) != 6 {
		t.Fatalf("expected 3 commands to create and 3 to remove, got %d: %q", len(sent), sent)
	}
}

func TestSelftestOverRCIRefusedRoute(t *testing.T) {
	k := exec.NewFakeKeenetic(t, exec.OwnerCfg)
	before := k.Running()
	k.RefuseOn("route object-group VwardTest")
	r := router.New(rci.New(k.Addr(), false), true)
	j := &journal.Journal{Dir: filepath.Join(t.TempDir(), "journal")}
	rep, err := selftest.Run(r, j, "NoSuchTunnel", time.Unix(1000, 0), true)
	if err != nil || rep.OK || len(rep.Steps) != 1 || rep.Steps[0].Outcome.State != "failed" {
		t.Fatalf("refused route: %v %+v", err, rep)
	}
	if after := k.Running(); after != before {
		t.Fatalf("not taken back:\n%s", after)
	}
	if j.Gate() != nil {
		t.Fatal("a proven compensation must not block")
	}
}
