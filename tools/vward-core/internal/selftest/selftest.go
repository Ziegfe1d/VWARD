// Package selftest is the first write of the routing core on a real router (owner
// 11.11.2026, instead of an emulator): one test group VWARD creates, checks and removes,
// through the same executor as every operation (CAS, pending record, one batch, a read that
// proves it, compensation). Nothing else is touched: a group of that name that already
// exists is not VWARD's and stops the test; the plan is built with the same protections and
// allowlist as every other one.
package selftest

import (
	"fmt"
	"strings"
	"time"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/exec"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/journal"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/plan"
)

const (
	Group  = "VwardTest"
	Domain = "vward-selftest.example.com"
)

// Step of the test: what was planned and how it ended.
type Step struct {
	Name     string
	Op       string
	Commands []string
	Outcome  journal.Outcome
	Reads    int
	Batches  int
	Took     time.Duration
}

type Report struct {
	Steps []Step
	OK    bool
	Why   string
}

func validTunnel(s string) bool {
	if s == "" || len(s) > 32 {
		return false
	}
	for _, c := range s {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '_' || c == '-' || c == '/' || c == '.') {
			return false
		}
	}
	return true
}

// Run: write=false plans both steps and sends nothing. tunnel "" tests the group alone.
func Run(r exec.Router, j *journal.Journal, tunnel string, now time.Time, write bool) (*Report, error) {
	if tunnel != "" && !validTunnel(tunnel) {
		return nil, fmt.Errorf("selftest: invalid tunnel name %q", tunnel)
	}
	rep := &Report{}
	cur, err := r.Read([]string{"groups", "routes"})
	if err != nil {
		return nil, fmt.Errorf("selftest: read: %w", err)
	}
	if _, ok := cur.Groups[Group]; ok {
		rep.Why = Group + " already exists: not created by this test, not touched"
		return rep, nil
	}
	if err := j.Gate(); err != nil {
		rep.Why = err.Error() + " (vward-core recover first)"
		return rep, nil
	}
	owned := map[string]bool{Group: true} // created by this plan, removed by the next one
	opts := ""
	if tunnel != "" {
		opts = "auto"
	}
	add, err := plan.Build(cur, plan.Desired{Groups: []plan.Group{{Name: Group, Include: []string{Domain}, Target: tunnel, Options: opts}}, OwnedGroups: owned}, nil)
	if err != nil {
		return nil, err
	}
	if len(add.Refused) > 0 {
		rep.Why = "refused: " + strings.Join(add.Refused, "; ")
		return rep, nil
	}
	id := fmt.Sprintf("selftest-%d", now.Unix())
	if !write {
		rep.Steps = append(rep.Steps, Step{Name: "add", Op: id + "-add", Commands: add.Commands()})
		del := []string{}
		if tunnel != "" {
			del = append(del, "dns-proxy no route object-group "+Group+" "+tunnel+" auto")
		}
		del = append(del, "no object-group fqdn "+Group+" include "+Domain, "no object-group fqdn "+Group)
		rep.Steps = append(rep.Steps, Step{Name: "remove", Op: id + "-remove", Commands: del})
		rep.OK, rep.Why = true, "plan only: nothing sent (--yes sends it)"
		return rep, nil
	}
	t0 := time.Now()
	res, err := exec.Run(r, j, id+"-add", cur, add)
	st := Step{Name: "add", Op: id + "-add", Commands: add.Commands(), Took: time.Since(t0)}
	if res != nil {
		st.Outcome, st.Reads, st.Batches = res.Outcome, res.Reads, res.Batches
	}
	rep.Steps = append(rep.Steps, st)
	if err != nil {
		rep.Why = "add: " + err.Error()
		return rep, nil
	}
	if st.Outcome.State != "done" {
		rep.Why = "add: " + st.Outcome.State + ": " + st.Outcome.Reason
		return rep, nil
	}
	after, err := r.Read([]string{"groups", "routes"})
	if err != nil {
		rep.Why = "read before removing: " + err.Error() + " - " + Group + " stays; run the test again to remove it"
		return rep, nil
	}
	del, err := plan.Build(after, plan.Desired{Groups: []plan.Group{{Name: Group, Delete: true}}, OwnedGroups: owned}, nil)
	if err != nil {
		return nil, err
	}
	t0 = time.Now()
	res, err = exec.Run(r, j, id+"-remove", after, del)
	st = Step{Name: "remove", Op: id + "-remove", Commands: del.Commands(), Took: time.Since(t0)}
	if res != nil {
		st.Outcome, st.Reads, st.Batches = res.Outcome, res.Reads, res.Batches
	}
	rep.Steps = append(rep.Steps, st)
	if err != nil {
		rep.Why = "remove: " + err.Error()
		return rep, nil
	}
	if st.Outcome.State != "done" {
		rep.Why = "remove: " + st.Outcome.State + ": " + st.Outcome.Reason
		return rep, nil
	}
	final, err := r.Read([]string{"groups", "routes"})
	if err != nil {
		rep.Why = "final read: " + err.Error()
		return rep, nil
	}
	if _, ok := final.Groups[Group]; ok || len(final.RoutesOf(Group)) > 0 {
		rep.Why = Group + " still present after removal"
		return rep, nil
	}
	rep.OK, rep.Why = true, "created, proven, removed, proven"
	return rep, nil
}
