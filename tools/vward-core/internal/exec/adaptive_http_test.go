package exec_test

import (
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/adaptive"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/exec"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/journal"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/rci"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/router"
)

// Autopodbor's write through the real path (HTTP RCI, narrow reads): the names go into
// AdaptiveAuto in one batch, everything else of the owner's configuration stays byte for byte.
func TestAdaptiveWriterOverRCI(t *testing.T) {
	k := exec.NewFakeKeenetic(t, exec.OwnerCfg)
	before := k.Running()
	r := router.New(rci.New(k.Addr(), false), true)
	w := &adaptive.Writer{R: r, J: &journal.Journal{Dir: filepath.Join(t.TempDir(), "j")}, Group: "AdaptiveAuto", Limit: 300, SaveEvery: time.Hour}
	b, err := w.Add([]string{"blocked-one.example.com", "blocked-two.example.com"}, time.Unix(1000, 0))
	if err != nil || len(b.Added) != 2 {
		t.Fatalf("%v %+v", err, b)
	}
	after := k.Running()
	want := strings.Replace(before, " include adaptive-one.example\n", " include adaptive-one.example\n include blocked-one.example.com\n include blocked-two.example.com\n", 1)
	if norm(after) != norm(want) {
		t.Fatalf("the configuration differs beyond the two names:\n--- want\n%s\n--- got\n%s", want, after)
	}
	if bs := k.Batches(); len(bs) != 1 {
		t.Fatalf("one batch, no save: %q", bs)
	}
}

func norm(s string) string { return strings.ReplaceAll(s, "    ", " ") }
