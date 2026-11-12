package adaptive

import (
	"context"
	"time"
)

// Taking names out of the group again, the route reconciler's rule: a name Autopodbor added is
// checked directly now and then; it leaves the group after 3 direct checks in a row that
// opened, at least 4 minutes apart. A failed check or one that could not tell starts over.

type ReconcileConfig struct {
	Every     time.Duration // a name is checked again after this
	Batch     int           // names checked per round
	Threshold int           // direct checks in a row before removal
	MinGap    time.Duration // between two counted checks
}

func DefaultReconcile() ReconcileConfig {
	return ReconcileConfig{Every: 30 * time.Minute, Batch: 8, Threshold: 3, MinGap: 4 * time.Minute}
}

// ReconcileEvent of one name.
type ReconcileEvent struct {
	Host   string
	Event  string // DIRECT_CONFIRM | DIRECT_FAIL | DIRECT_UNKNOWN | REMOVE
	Streak int
	Why    string
}

// Reconcile checks the due owned names and returns the ones to take out (Streak reached).
func Reconcile(ctx context.Context, o *Owned, p Prober, wanDev string, rc ReconcileConfig, now time.Time) ([]string, []ReconcileEvent) {
	var remove []string
	var ev []ReconcileEvent
	for _, h := range o.Due(now, rc.Every, rc.Batch) {
		n := o.Names[h]
		r := p.Probe(ctx, h, wanDev)
		n.Checked = now
		switch r.Verdict {
		case Open:
			if !n.LastOK.IsZero() && now.Sub(n.LastOK) < rc.MinGap {
				continue
			}
			n.Streak++
			n.LastOK = now
			if n.Streak >= rc.Threshold {
				remove = append(remove, h)
				ev = append(ev, ReconcileEvent{h, "REMOVE", n.Streak, r.Why})
			} else {
				ev = append(ev, ReconcileEvent{h, "DIRECT_CONFIRM", n.Streak, r.Why})
			}
		case Blocked:
			n.Streak, n.LastOK = 0, time.Time{}
			ev = append(ev, ReconcileEvent{h, "DIRECT_FAIL", 0, r.Why})
		default:
			// Filtered by DNS (0.0.0.0): the same DNS answers through VPN, so VPN gives nothing -
			// out of the group (ad.doubleclick.net in the owner's autopick, 12.11.2026).
			if r.Why == "dns blocked" {
				remove = append(remove, h)
				ev = append(ev, ReconcileEvent{h, "REMOVE", n.Streak, r.Why})
				continue
			}
			n.Streak, n.LastOK = 0, time.Time{}
			ev = append(ev, ReconcileEvent{h, "DIRECT_UNKNOWN", 0, r.Why})
		}
	}
	return remove, ev
}
