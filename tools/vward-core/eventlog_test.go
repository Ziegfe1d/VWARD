package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// Owner 12.11.2026: the journal goes to the USB drive in batches, a start, a stop and a failure at once.
func TestEventLogBatches(t *testing.T) {
	p := filepath.Join(t.TempDir(), "core.log")
	l := &eventLog{path: p, every: time.Hour}
	lines := func() int {
		b, _ := os.ReadFile(p)
		return strings.Count(string(b), "\n")
	}
	l.put("DIRECT_OK", "a.example.com", "")
	l.put("ADDED", "b.example.com", "AdaptiveAuto")
	if n := lines(); n != 0 {
		t.Fatalf("routine lines written at once: %d", n)
	}
	l.put("ADD_FAILED", "c.example.com", "router")
	if n := lines(); n != 3 {
		t.Fatalf("a failure writes what waits and itself: %d", n)
	}
	for i := 0; i < logBatch; i++ {
		l.put("DIRECT_OK", "d.example.com", "")
	}
	if n := lines(); n != 3+logBatch {
		t.Fatalf("a full batch is written: %d", n)
	}
	l.put("STATS", "-", "x")
	l.flush()
	if n := lines(); n != 4+logBatch {
		t.Fatalf("flush writes what waits: %d", n)
	}
	old := &eventLog{path: p, every: time.Nanosecond}
	old.put("DIRECT_OK", "e.example.com", "")
	time.Sleep(time.Millisecond)
	old.put("DIRECT_OK", "f.example.com", "")
	if n := lines(); n != 6+logBatch {
		t.Fatalf("lines waiting longer than every are written: %d", n)
	}
}
