package selftest

import (
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/journal"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/ndm"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/rci"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/recovery"
)

// fakeRouter: the router's configuration as the core's own model; a batch applies its
// commands one by one (Keenetic does the same) and can refuse one or lose the answer.
type fakeRouter struct {
	m        *ndm.Model
	refuseOn string // a command containing this is refused, the rest of the batch applies
	loseAt   int    // batch number (1-based) whose answer is lost after applying (0: none)
	failRead bool
	batches  [][]string
}

func newRouter(t *testing.T, cfg string) *fakeRouter {
	t.Helper()
	return &fakeRouter{m: ndm.ParseRunning(cfg)}
}

func (f *fakeRouter) Read(areas []string) (*ndm.Model, error) {
	if f.failRead {
		return nil, errors.New("read refused")
	}
	return f.m.Clone(), nil
}

func (f *fakeRouter) Send(cmds []string) ([]rci.Result, error) {
	f.batches = append(f.batches, cmds)
	var out []rci.Result
	for _, c := range cmds {
		if c == "system configuration save" {
			out = append(out, rci.Result{Command: c})
			continue
		}
		if f.refuseOn != "" && strings.Contains(c, f.refuseOn) {
			out = append(out, rci.Result{Command: c, Status: "error", Message: "refused"})
			continue
		}
		if err := f.m.Apply(c); err != nil {
			return nil, err
		}
		out = append(out, rci.Result{Command: c})
	}
	if f.loseAt == len(f.batches) {
		f.loseAt = 0
		return nil, errors.New("connection closed")
	}
	return out, nil
}

const owner = `object-group fqdn Youtube
 include youtube.com
!
object-group fqdn AdaptiveAuto
 include example.org
!
dns-proxy
 route object-group Youtube OpkgTun4 auto
 route object-group AdaptiveAuto OpkgTun4 auto
!
ip route 8.8.8.0 255.255.255.0 OpkgTun4 auto
`

func untouched(t *testing.T, f *fakeRouter, before *ndm.Model) {
	t.Helper()
	for _, a := range []string{"group:Youtube", "route:Youtube", "group:AdaptiveAuto", "route:AdaptiveAuto"} {
		if f.m.Fingerprint(a) != before.Fingerprint(a) {
			t.Fatalf("%s changed: %q -> %q", a, before.Fingerprint(a), f.m.Fingerprint(a))
		}
	}
}

func TestCreateProveRemove(t *testing.T) {
	f := newRouter(t, owner)
	before := f.m.Clone()
	j := &journal.Journal{Dir: t.TempDir()}
	rep, err := Run(f, j, "OpkgTun4", time.Unix(1000, 0), true)
	if err != nil || !rep.OK {
		t.Fatalf("selftest: %v %+v", err, rep)
	}
	if _, ok := f.m.Groups[Group]; ok || len(f.m.RoutesOf(Group)) > 0 {
		t.Fatal("the test group stayed")
	}
	untouched(t, f, before)
	if len(rep.Steps) != 2 || rep.Steps[0].Outcome.State != "done" || rep.Steps[1].Outcome.State != "done" {
		t.Fatalf("steps: %+v", rep.Steps)
	}
	add := strings.Join(rep.Steps[0].Commands, "\n")
	for _, want := range []string{"object-group fqdn VwardTest include " + Domain, "dns-proxy route object-group VwardTest OpkgTun4 auto"} {
		if !strings.Contains(add, want) {
			t.Fatalf("add batch lacks %q:\n%s", want, add)
		}
	}
	for _, b := range f.batches {
		for _, c := range b {
			if c != "system configuration save" && !strings.Contains(c, Group) {
				t.Fatalf("a command outside the test group: %q", c)
			}
		}
	}
	if j.Gate() != nil {
		t.Fatal("the journal blocks after a clean test")
	}
}

func TestPlanOnlySendsNothing(t *testing.T) {
	f := newRouter(t, owner)
	rep, err := Run(f, &journal.Journal{Dir: t.TempDir()}, "OpkgTun4", time.Unix(1000, 0), false)
	if err != nil || !rep.OK || len(f.batches) != 0 || len(rep.Steps) != 2 {
		t.Fatalf("plan only: %v %+v batches=%d", err, rep, len(f.batches))
	}
}

func TestExistingGroupNotTouched(t *testing.T) {
	f := newRouter(t, owner+"object-group fqdn VwardTest\n include mine.example.net\n!\n")
	before := f.m.Clone()
	rep, err := Run(f, &journal.Journal{Dir: t.TempDir()}, "OpkgTun4", time.Unix(1000, 0), true)
	if err != nil || rep.OK || len(f.batches) != 0 || !strings.Contains(rep.Why, "already exists") {
		t.Fatalf("existing group: %v %+v", err, rep)
	}
	if f.m.Fingerprint("group:VwardTest") != before.Fingerprint("group:VwardTest") {
		t.Fatal("the owner's group of that name changed")
	}
}

func TestRefusedRouteCompensated(t *testing.T) {
	f := newRouter(t, owner)
	f.refuseOn = "dns-proxy route object-group VwardTest"
	before := f.m.Clone()
	j := &journal.Journal{Dir: t.TempDir()}
	rep, err := Run(f, j, "NoSuchTunnel", time.Unix(1000, 0), true)
	if err != nil || rep.OK || rep.Steps[0].Outcome.State != "failed" {
		t.Fatalf("refused route: %v %+v", err, rep)
	}
	if _, ok := f.m.Groups[Group]; ok {
		t.Fatal("the half-made test group was not taken back")
	}
	untouched(t, f, before)
	if j.Gate() != nil {
		t.Fatal("a compensated failure must not block")
	}
}

func TestInvalidTunnelRefused(t *testing.T) {
	f := newRouter(t, owner)
	if _, err := Run(f, &journal.Journal{Dir: t.TempDir()}, "OpkgTun4; erase", time.Unix(1000, 0), true); err == nil || len(f.batches) != 0 {
		t.Fatal("an odd tunnel name must stop the test before anything is sent")
	}
}

// A lost answer and no read after it: the add stays unknown and blocks; recovery reads the
// router and closes it by evidence; the next test runs.
func TestRecoveryAfterLostAnswer(t *testing.T) {
	f := newRouter(t, owner)
	f.loseAt = 1
	j := &journal.Journal{Dir: t.TempDir()}
	// The answer is lost and so is the read after it.
	r := &readFailsAfterSend{fakeRouter: f}
	rep, err := Run(r, j, "OpkgTun4", time.Unix(1000, 0), true)
	if err != nil || rep.OK || rep.Steps[0].Outcome.State != "unknown" {
		t.Fatalf("lost answer: %v %+v", err, rep)
	}
	if j.Gate() == nil {
		t.Fatal("an unknown operation must block")
	}
	again, _ := Run(f, j, "OpkgTun4", time.Unix(2000, 0), true)
	if again.OK || len(f.batches) != 1 {
		t.Fatalf("a blocked journal must stop the next test: %+v", again)
	}
	reps, err := recovery.Run(f, j, true)
	if err != nil || len(reps) != 1 || reps[0].Now != "done" {
		t.Fatalf("recovery: %v %+v", err, reps)
	}
	if j.Gate() != nil {
		t.Fatal("recovery must unblock")
	}
}

// readFailsAfterSend: every read after the first batch fails once.
type readFailsAfterSend struct {
	*fakeRouter
	failed bool
}

func (r *readFailsAfterSend) Read(areas []string) (*ndm.Model, error) {
	if len(r.batches) > 0 && !r.failed {
		r.failed = true
		return nil, errors.New("no answer")
	}
	return r.fakeRouter.Read(areas)
}
