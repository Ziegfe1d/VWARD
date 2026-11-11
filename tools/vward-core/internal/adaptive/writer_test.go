package adaptive

import (
	"errors"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/journal"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/ndm"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/rci"
)

type modelRouter struct {
	m       *ndm.Model
	batches [][]string
	before  func() // runs before each read (another writer)
}

func (f *modelRouter) Read([]string) (*ndm.Model, error) {
	if f.before != nil {
		f.before()
	}
	return f.m.Clone(), nil
}

func (f *modelRouter) Send(cmds []string) ([]rci.Result, error) {
	f.batches = append(f.batches, cmds)
	var out []rci.Result
	for _, c := range cmds {
		if c != "system configuration save" {
			if err := f.m.Apply(c); err != nil {
				return nil, err
			}
		}
		out = append(out, rci.Result{Command: c})
	}
	return out, nil
}

func writer(t *testing.T, cfg string) (*Writer, *modelRouter) {
	r := &modelRouter{m: ndm.ParseRunning(cfg)}
	return &Writer{R: r, J: &journal.Journal{Dir: t.TempDir()}, Group: "AdaptiveAuto", Limit: 300, SaveEvery: 30 * time.Minute, KeepOps: 3}, r
}

func TestWriterOneBatchOnlyIncludes(t *testing.T) {
	w, r := writer(t, cfgText)
	yt := r.m.Fingerprint("group:Youtube")
	b, err := w.Add([]string{"b.example.com", "a.example.com", "a.example.com", "x.known.example.net"}, time.Unix(1000, 0))
	if err != nil || len(b.Added) != 2 {
		t.Fatalf("add: %v %+v", err, b)
	}
	if len(r.batches) != 1 || len(r.batches[0]) != 2 {
		t.Fatalf("one batch of two includes, no save: %q", r.batches)
	}
	for _, c := range r.batches[0] {
		if !strings.HasPrefix(c, "object-group fqdn AdaptiveAuto include ") {
			t.Fatalf("not an include: %q", c)
		}
	}
	if r.m.Fingerprint("group:Youtube") != yt || len(r.m.RoutesOf("AdaptiveAuto")) != 1 {
		t.Fatal("something besides the includes changed")
	}
	// Saved on the writer's schedule, not after the batch.
	if saved, _ := w.Flush(time.Unix(1000, 0), false); !saved {
		t.Fatal("the first flush saves")
	}
	w.Add([]string{"c.example.com"}, time.Unix(1100, 0))
	if saved, _ := w.Flush(time.Unix(1100, 0), false); saved {
		t.Fatal("saved again within SaveEvery")
	}
	if saved, _ := w.Flush(time.Unix(1100, 0), true); !saved {
		t.Fatal("a forced flush (stop) saves")
	}
}

func TestWriterObserveSendsNothing(t *testing.T) {
	w, r := writer(t, cfgText)
	w.Observe = true
	b, err := w.Add([]string{"a.example.com"}, time.Unix(1000, 0))
	if err != nil || len(b.Would) != 1 || len(r.batches) != 0 {
		t.Fatalf("observe: %v %+v %q", err, b, r.batches)
	}
}

func TestWriterLimit(t *testing.T) {
	w, r := writer(t, cfgText)
	w.Limit = 2
	b, err := w.Add([]string{"a.example.com", "b.example.com"}, time.Unix(1000, 0))
	if err != nil || len(b.Added) != 1 || len(b.Skipped) != 1 {
		t.Fatalf("one place left: %v %+v", err, b)
	}
	b, err = w.Add([]string{"c.example.com"}, time.Unix(1001, 0))
	if err != nil || len(b.Added) != 0 || !strings.Contains(b.Why, "full") || len(r.batches) != 1 {
		t.Fatalf("full: %v %+v", err, b)
	}
}

func TestWriterNeedsRoutedGroup(t *testing.T) {
	w, r := writer(t, "object-group fqdn AdaptiveAuto\n include x.example.net\n!\n")
	if _, err := w.Add([]string{"a.example.com"}, time.Unix(1000, 0)); !errors.Is(err, ErrNoGroup) || len(r.batches) != 0 {
		t.Fatalf("a group without a VPN route: %v %q", err, r.batches)
	}
	w2, r2 := writer(t, "")
	if _, err := w2.Add([]string{"a.example.com"}, time.Unix(1000, 0)); !errors.Is(err, ErrNoGroup) || len(r2.batches) != 0 {
		t.Fatalf("no group: %v", err)
	}
}

// Another writer (the reconciler, the Panel) changes the group between the plan and the batch:
// nothing is sent, the names wait for the next batch.
func TestWriterChangedSincePlan(t *testing.T) {
	w, r := writer(t, cfgText)
	n := 0
	r.before = func() {
		n++
		if n == 2 { // the CAS read right before the batch
			r.m.Apply("no object-group fqdn AdaptiveAuto include known.example.net")
		}
	}
	if _, err := w.Add([]string{"a.example.com"}, time.Unix(1000, 0)); err == nil || len(r.batches) != 0 {
		t.Fatalf("changed since the plan must stop the batch: %v %q", err, r.batches)
	}
	if w.J.Gate() != nil {
		t.Fatal("a refused batch must not block")
	}
}

func TestWriterJournalPruned(t *testing.T) {
	w, _ := writer(t, cfgText)
	for i, h := range []string{"a.example.com", "b.example.com", "c.example.com", "d.example.com", "e.example.com"} {
		if _, err := w.Add([]string{h}, time.Unix(int64(1000+i), 0)); err != nil {
			t.Fatal(err)
		}
	}
	ents, _ := readDir(w.J.Dir)
	if len(ents) != 3 {
		t.Fatalf("kept %d operations, want 3: %v", len(ents), ents)
	}
}

func readDir(d string) ([]string, error) {
	es, err := os.ReadDir(d)
	var out []string
	for _, e := range es {
		out = append(out, e.Name())
	}
	return out, err
}
