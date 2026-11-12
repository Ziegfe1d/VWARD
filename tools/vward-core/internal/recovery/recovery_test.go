package recovery

import (
	"errors"
	"testing"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/journal"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/ndm"
)

type reader struct {
	m   *ndm.Model
	err error
}

func (r reader) Read([]string) (*ndm.Model, error) { return r.m, r.err }

const base = "object-group fqdn AdaptiveAuto\n include a.example\n!\n"

func pending(t *testing.T, j *journal.Journal, op string) {
	t.Helper()
	pre := ndm.ParseRunning(base)
	post := pre.Clone()
	if err := post.Apply("object-group fqdn AdaptiveAuto include b.example"); err != nil {
		t.Fatal(err)
	}
	a := "group:AdaptiveAuto"
	if err := j.Begin(journal.Pending{Op: op, Commands: []string{"object-group fqdn AdaptiveAuto include b.example"},
		Pre: map[string]string{a: pre.Fingerprint(a)}, Post: map[string]string{a: post.Fingerprint(a)}}); err != nil {
		t.Fatal(err)
	}
}

func TestResolvedByEvidence(t *testing.T) {
	for _, c := range []struct {
		name, cfg, want string
	}{
		{"applied", base + "object-group fqdn AdaptiveAuto\n include b.example\n!\n", "done"},
		{"not applied", base, "failed"},
		{"something else", "object-group fqdn AdaptiveAuto\n include z.example\n!\n", "open"},
	} {
		t.Run(c.name, func(t *testing.T) {
			j := &journal.Journal{Dir: t.TempDir()}
			pending(t, j, "op1")
			m := ndm.ParseRunning(c.cfg)
			if c.name == "applied" {
				m = ndm.ParseRunning(base)
				m.Apply("object-group fqdn AdaptiveAuto include b.example")
			}
			// A report first: nothing written.
			reps, err := Run(reader{m: m}, j, false)
			if err != nil || len(reps) != 1 || reps[0].Now != c.want || j.Gate() == nil {
				t.Fatalf("report: %v %+v", err, reps)
			}
			reps, err = Run(reader{m: m}, j, true)
			if err != nil || reps[0].Now != c.want {
				t.Fatalf("resolve: %v %+v", err, reps)
			}
			if (j.Gate() == nil) != (c.want != "open") {
				t.Fatalf("gate after %s", c.want)
			}
		})
	}
}

func TestUnreadableRouterKeepsOpen(t *testing.T) {
	j := &journal.Journal{Dir: t.TempDir()}
	pending(t, j, "op1")
	reps, err := Run(reader{err: errors.New("down")}, j, true)
	if err != nil || reps[0].Now != "open" || j.Gate() == nil {
		t.Fatalf("%v %+v", err, reps)
	}
}
