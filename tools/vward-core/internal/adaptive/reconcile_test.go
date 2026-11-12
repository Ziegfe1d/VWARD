package adaptive

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestOwnedImportForgetSave(t *testing.T) {
	dir := t.TempDir()
	shell := filepath.Join(dir, "adaptive-persist.txt")
	os.WriteFile(shell, []byte("a.example.com\nGONE.example.com\nB.Example.com\nnot a name\n"), 0o644)
	o, _ := LoadOwned(filepath.Join(dir, "owned.json"))
	in := map[string]bool{"a.example.com": true, "b.example.com": true, "owner.example.com": true}
	if n := o.ImportShell(shell, in, time.Unix(1, 0)); n != 2 || o.Names["b.example.com"] == nil || o.Names["owner.example.com"] != nil {
		t.Fatalf("import: %d %v", n, o.Names)
	}
	if n := o.ImportShell(shell, in, time.Unix(2, 0)); n != 0 {
		t.Fatal("imported twice")
	}
	if gone := o.Forget(map[string]bool{"a.example.com": true}, time.Unix(100, 0)); len(gone) != 1 || len(o.Names) != 1 || o.Refused["b.example.com"].IsZero() {
		t.Fatalf("forget: %v %v", gone, o.Names)
	}
	if left := o.StillRefused(time.Unix(100, 0).Add(RefuseFor - time.Hour)); left["b.example.com"] != time.Hour {
		t.Fatalf("still refused: %v", left)
	}
	if left := o.StillRefused(time.Unix(100, 0).Add(RefuseFor + time.Hour)); len(left) != 0 || len(o.Refused) != 0 {
		t.Fatalf("refusal over: %v", left)
	}
	o.Refused["b.example.com"] = time.Unix(100, 0)
	if err := o.Save(); err != nil {
		t.Fatal(err)
	}
	back, err := LoadOwned(o.Path)
	if err != nil || len(back.Names) != 1 || back.Names["a.example.com"] == nil || back.Refused["b.example.com"].IsZero() {
		t.Fatalf("reload: %v %v", err, back.Names)
	}
}

func TestDueOrderAndLimit(t *testing.T) {
	o := &Owned{Names: map[string]*Name{
		"new.example.com":   {},
		"old.example.com":   {Checked: time.Unix(100, 0)},
		"fresh.example.com": {Checked: time.Unix(1000, 0)},
	}}
	due := o.Due(time.Unix(1100, 0), 500*time.Second, 1)
	if len(due) != 1 || due[0] != "new.example.com" {
		t.Fatalf("due: %v", due)
	}
	if due := o.Due(time.Unix(1100, 0), 500*time.Second, 8); strings.Join(due, ",") != "new.example.com,old.example.com" {
		t.Fatalf("due all: %v", due)
	}
}

// 3 direct checks in a row, at least MinGap apart; a failure or an unknown starts over.
func TestReconcileStreak(t *testing.T) {
	rc := ReconcileConfig{Every: time.Minute, Batch: 8, Threshold: 3, MinGap: 4 * time.Minute}
	o := &Owned{Names: map[string]*Name{"x.example.com": {}}}
	p := &scripted{ans: map[string][]Verdict{"ppp0 x.example.com": {O, O, B, O, U, O, O, O}}}
	at := func(min int) ([]string, []ReconcileEvent) {
		return Reconcile(context.Background(), o, p, "ppp0", rc, time.Unix(int64(min*60), 0))
	}
	steps := []struct {
		min    int
		event  string
		streak int
	}{
		{0, "DIRECT_CONFIRM", 1},
		{2, "", 1}, // too soon after the last success: not counted
		{6, "DIRECT_FAIL", 0},
		{8, "DIRECT_CONFIRM", 1},
		{13, "DIRECT_UNKNOWN", 0},
		{15, "DIRECT_CONFIRM", 1},
		{20, "DIRECT_CONFIRM", 2},
		{25, "REMOVE", 3},
	}
	for _, s := range steps {
		rm, ev := at(s.min)
		got := ""
		if len(ev) == 1 {
			got = ev[0].Event
		}
		if got != s.event || o.Names["x.example.com"].Streak != s.streak {
			t.Fatalf("minute %d: %q streak %d, want %q %d", s.min, got, o.Names["x.example.com"].Streak, s.event, s.streak)
		}
		if (s.event == "REMOVE") != (len(rm) == 1) {
			t.Fatalf("minute %d: remove %v", s.min, rm)
		}
	}
}

func TestWriterRemoveOnlyIncludes(t *testing.T) {
	w, r := writer(t, cfgText)
	w.Add([]string{"a.example.com", "b.example.com"}, time.Unix(1000, 0))
	r.batches = nil
	b, err := w.Remove([]string{"a.example.com", "not-there.example.com"}, time.Unix(1100, 0))
	if err != nil || len(b.Removed) != 1 || b.Removed[0] != "a.example.com" {
		t.Fatalf("remove: %v %+v", err, b)
	}
	if len(r.batches) != 1 || len(r.batches[0]) != 1 || r.batches[0][0] != "no object-group fqdn AdaptiveAuto include a.example.com" {
		t.Fatalf("batch: %q", r.batches)
	}
	if !contains(r.m.Groups["AdaptiveAuto"].Include, "b.example.com") || len(r.m.RoutesOf("AdaptiveAuto")) != 1 {
		t.Fatal("more than the one name changed")
	}
}

func TestWriterRemoveKeepsLastName(t *testing.T) {
	w, r := writer(t, cfgText)
	b, err := w.Remove([]string{"known.example.net"}, time.Unix(1000, 0))
	if err != nil || len(b.Removed) != 0 || len(r.batches) != 0 || len(r.m.Groups["AdaptiveAuto"].Include) != 1 {
		t.Fatalf("the last name must stay: %v %+v %q", err, b, r.batches)
	}
}

func TestWriterRemoveObserve(t *testing.T) {
	w, r := writer(t, cfgText)
	w.Add([]string{"a.example.com"}, time.Unix(1000, 0))
	r.batches = nil
	w.Observe = true
	b, err := w.Remove([]string{"a.example.com"}, time.Unix(1100, 0))
	if err != nil || len(b.Would) != 1 || len(r.batches) != 0 {
		t.Fatalf("observe: %v %+v", err, b)
	}
}

func contains(a []string, s string) bool {
	for _, x := range a {
		if x == s {
			return true
		}
	}
	return false
}

// A name the owner took out is skipped, not checked, until the refusal runs out.
func TestRefusedNotChecked(t *testing.T) {
	e, p := engine(map[string][]Verdict{"ppp0 x.example.com": {B, B}, "opkgtun4 x.example.com": {O, O}, "ppp0 ya.ru": {O}})
	now := time.Unix(1000, 0)
	e.Now = func() time.Time { return now }
	e.Refuse("x.example.com", time.Hour)
	if r := e.Check(context.Background(), "x.example.com"); r.Outcome != Skip || len(p.calls) != 0 {
		t.Fatalf("refused: %+v %v", r, p.calls)
	}
	now = now.Add(2 * time.Hour)
	if r := e.Check(context.Background(), "x.example.com"); r.Outcome != Add {
		t.Fatalf("after the refusal: %+v", r)
	}
}
