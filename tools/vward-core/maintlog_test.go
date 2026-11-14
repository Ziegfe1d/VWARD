package main

import (
	"reflect"
	"testing"

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
