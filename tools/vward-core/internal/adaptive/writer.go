package adaptive

import (
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/exec"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/journal"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/ndm"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/plan"
)

// Writer puts names into the group through the executor: the names found within a few
// seconds go as one batch (CAS read, pending record, one RCI request, a read that proves it,
// compensation). Only «include» lines of this one group are ever sent: no route, no other
// group, no removal (taking names out stays with the route reconciler for now). The
// configuration is saved at most every SaveEvery, not after every batch (the USB stick).
type Writer struct {
	R         exec.Router
	J         *journal.Journal
	Group     string
	Limit     int           // names the group may hold (Keenetic keeps 300)
	Observe   bool          // only say what would be added
	SaveEvery time.Duration // 0: after every batch
	KeepOps   int           // closed operations kept in the journal

	dirty    bool
	lastSave time.Time
	seq      int
}

// Batch result.
type Batch struct {
	Added   []string // in the group, proven
	Would   []string // observation: what would have been added
	Skipped []string // already in the group, or no room
	Model   *ndm.Model
	Why     string // why nothing was written ("" when written)
}

var ErrNoGroup = errors.New("adaptive: the group or its VPN route is missing")

// Add: one batch of names. now names the operation.
func (w *Writer) Add(hosts []string, now time.Time) (*Batch, error) {
	b := &Batch{}
	cur, err := w.R.Read([]string{"groups", "routes"})
	if err != nil {
		return nil, fmt.Errorf("adaptive: read: %w", err)
	}
	b.Model = cur
	g, ok := cur.Groups[w.Group]
	routes := cur.RoutesOf(w.Group)
	if !ok || len(routes) == 0 {
		b.Why = w.Group + " missing or not routed to the VPN: nothing would go to the VPN"
		return b, ErrNoGroup
	}
	if len(routes) > 1 {
		b.Why = w.Group + " has more than one route: not changed"
		return b, ErrNoGroup
	}
	have := map[string]bool{}
	for _, d := range g.Include {
		have[d] = true
	}
	room := w.Limit - len(g.Include)
	var add []string
	seen := map[string]bool{}
	sort.Strings(hosts)
	for _, h := range hosts {
		if seen[h] || coveredBy(h, have) != "" {
			b.Skipped = append(b.Skipped, h)
			continue
		}
		seen[h] = true
		if len(add) >= room {
			b.Skipped = append(b.Skipped, h)
			continue
		}
		add = append(add, h)
	}
	if len(add) == 0 {
		if room <= 0 {
			b.Why = fmt.Sprintf("%s is full (%d of %d)", w.Group, len(g.Include), w.Limit)
		} else {
			b.Why = "nothing new"
		}
		return b, nil
	}
	if w.Observe {
		b.Would = add
		b.Why = "observation: nothing sent"
		return b, nil
	}
	r := routes[0]
	want := plan.Desired{
		Groups:      []plan.Group{{Name: w.Group, Include: append(append([]string(nil), g.Include...), add...), Target: r.Target, Options: r.Options}},
		OwnedGroups: map[string]bool{w.Group: true},
	}
	p, err := plan.Build(cur, want, nil)
	if err != nil {
		return nil, err
	}
	for _, s := range p.Steps {
		if s.Area != "group:"+w.Group || !strings.HasPrefix(s.Cmd, "object-group fqdn "+w.Group+" include ") {
			return nil, fmt.Errorf("adaptive: the plan goes beyond adding names: %q", s.Cmd)
		}
	}
	if len(p.Refused) > 0 {
		b.Why = "refused: " + strings.Join(p.Refused, "; ")
	}
	if len(p.Steps) == 0 {
		return b, nil
	}
	w.seq++
	op := fmt.Sprintf("adaptive-%d-%d", now.Unix(), w.seq)
	res, err := exec.RunWith(w.R, w.J, op, cur, p, exec.Options{NoSave: w.SaveEvery > 0})
	if err != nil {
		return b, err
	}
	if res.Outcome.State != "done" {
		b.Why = res.Outcome.State + ": " + res.Outcome.Reason
		return b, nil
	}
	for _, s := range p.Steps {
		b.Added = append(b.Added, strings.TrimPrefix(s.Cmd, "object-group fqdn "+w.Group+" include "))
	}
	w.dirty = w.SaveEvery > 0
	if w.KeepOps > 0 {
		w.J.Prune("adaptive-", w.KeepOps)
	}
	return b, nil
}

// Flush saves the configuration when a batch was written and SaveEvery has passed.
func (w *Writer) Flush(now time.Time, force bool) (bool, error) {
	if !w.dirty || (!force && now.Sub(w.lastSave) < w.SaveEvery) {
		return false, nil
	}
	res, err := w.R.Send([]string{"system configuration save"})
	if err != nil {
		return false, err
	}
	if len(res) != 1 || res[0].Status == "error" {
		return false, fmt.Errorf("adaptive: configuration save refused")
	}
	w.dirty, w.lastSave = false, now
	return true, nil
}
