package main

import (
	"os"
	"reflect"
	"testing"
	"time"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/adaptive"
)

// Owner's diagnostics 13.11.2026: the journal was nearly all «MAINT_DIRECT_FAIL … streak=0/3», a name
// still blocked at every round. Only a change is a line of its own; the rest is one line with the count.
func TestMaintLogOnlyChanges(t *testing.T) {
	prev := map[string]int{"a.example": 0, "b.example": 2, "c.example": 0, "d.example": 1, "e.example": 0, "f.example": 2}
	ev := []adaptive.ReconcileEvent{
		{Host: "a.example", Event: "DIRECT_FAIL", Why: "tls: timeout"},           // still blocked: counted
		{Host: "b.example", Event: "DIRECT_FAIL", Why: "tls: timeout"},           // a streak broken: a line
		{Host: "c.example", Event: "DIRECT_UNKNOWN", Why: "no address"},          // still unknown: counted
		{Host: "d.example", Event: "DIRECT_CONFIRM", Streak: 2, Why: "http 200"}, // a step to removal: a line
		{Host: "e.example", Event: "DIRECT_FAIL", Why: "connect: timeout"},       // still blocked: counted
		{Host: "f.example", Event: "REMOVE", Streak: 3, Why: "http 200"},         // logged where it is removed
	}
	var got [][3]string
	maintLog(prev, ev, 3, func(code, host, detail string) { got = append(got, [3]string{code, host, detail}) })
	want := [][3]string{
		{"MAINT_DIRECT_FAIL", "b.example", "streak=0/3 tls: timeout"},
		{"MAINT_DIRECT_CONFIRM", "d.example", "streak=2/3 http 200"},
		{"MAINT_STILL_BLOCKED", "-", "still=2 unknown=1"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("maintenance lines:\n got %v\nwant %v", got, want)
	}
	got = nil
	maintLog(map[string]int{}, nil, 3, func(code, host, detail string) { got = append(got, [3]string{code, host, detail}) })
	if got != nil {
		t.Fatalf("a round with nothing checked writes nothing: %v", got)
	}
}

// fix.39: a failure through the VPN too is a step to removal - a line; a VPN that does not work
// is returned to the caller (said once an hour), removals are written where the name is taken out.
func TestMaintLogVPN(t *testing.T) {
	ev := []adaptive.ReconcileEvent{
		{Host: "-", Event: "VPN_DOWN", Why: "x"},
		{Host: "a.example", Event: "VPN_FAIL", Streak: 2, Why: "direct: connect: timeout; vpn: connect: timeout"},
		{Host: "b.example", Event: "DROP", Streak: 3, Why: "direct: connect: timeout; vpn: connect: refused"},
		{Host: "c.example", Event: "REMOVE", Streak: 3, Why: "http 200"},
		{Host: "d.example", Event: "REMOVE", Why: "dns blocked"},
	}
	var got [][3]string
	down := maintLog(map[string]int{}, ev, 3, func(code, host, detail string) { got = append(got, [3]string{code, host, detail}) })
	want := [][3]string{{"MAINT_NO_PATH", "a.example", "fails=2/3 direct: connect: timeout; vpn: connect: timeout"}}
	if !down || !reflect.DeepEqual(got, want) {
		t.Fatalf("down %v, lines %v", down, got)
	}
	if maintLog(map[string]int{}, ev[1:], 3, func(string, string, string) {}) {
		t.Fatal("no VPN_DOWN - not down")
	}
	l := removalLines(ev)
	if !l["b.example"].drop || l["b.example"].why != "opens neither directly nor through the VPN: direct: connect: timeout; vpn: connect: refused" ||
		l["c.example"] != (removal{false, "opened directly 3 times in a row"}) || l["d.example"] != (removal{false, "dns blocked"}) || len(l) != 3 {
		t.Fatalf("removal lines: %+v", l)
	}
}

func TestModeFiles(t *testing.T) {
	dir := t.TempDir()
	off := dir + "/adaptive.disabled"
	list := splitList(" " + dir + "/core.observe, " + off + ",")
	if len(list) != 2 || anyExists(list) {
		t.Fatalf("no file - not paused: %v", list)
	}
	os.WriteFile(off, nil, 0o644)
	if !anyExists(list) || anyExists(nil) {
		t.Fatal("the switch file pauses the writes")
	}
	if someNames(nil, 3) != "" || someNames([]string{"a", "b", "c", "d"}, 3) != ": a, b, c and 1 more" {
		t.Fatalf("names: %q", someNames([]string{"a", "b", "c", "d"}, 3))
	}
}

// fix.39.2: the first blocked site is written at once, not up to 10 s later; then at most one
// write a batch time, as before.
func TestWriteNow(t *testing.T) {
	t0 := time.Unix(1000, 0)
	if !writeNow(time.Time{}, t0, 10*time.Second) {
		t.Fatal("never written: at once")
	}
	if writeNow(t0, t0.Add(3*time.Second), 10*time.Second) {
		t.Fatal("3 s after a write: wait for the ticker")
	}
	if !writeNow(t0, t0.Add(10*time.Second), 10*time.Second) {
		t.Fatal("a batch time after a write: at once")
	}
}
