package adaptive

import (
	"context"
	"time"
)

// Taking names out of the group again, the route reconciler's rule: a name Autopodbor added is
// checked directly now and then; it leaves the group after 3 direct checks in a row that
// opened, at least 4 minutes apart. A failed check or one that could not tell starts over.
//
// A name that does not open directly is checked through the VPN too (owner's journal
// 12.11.2026: names with no HTTPS at all - an NTP pool, a tracker, an FTP mirror - stayed in the
// VPN for good). It leaves the group after 3 such checks in a row, at least 4 minutes apart,
// that opened through neither path - and only while the VPN itself works: its control sites
// must open through it, else nothing is counted (a tunnel that is down proves nothing about a
// site). «Could not check» through the VPN counts nothing either.

type ReconcileConfig struct {
	Every      time.Duration // a name is checked again after this
	Batch      int           // names checked per round
	Threshold  int           // checks in a row before removal (direct opened; or neither path)
	MinGap     time.Duration // between two counted checks
	TunnelDev  string        // the VPN's device ("": the VPN is not checked, as before fix.39)
	VPNControl []string      // sites that must open through the VPN for a VPN failure to count
}

func DefaultReconcile() ReconcileConfig {
	return ReconcileConfig{Every: 30 * time.Minute, Batch: 8, Threshold: 3, MinGap: 4 * time.Minute,
		VPNControl: []string{"www.google.com", "github.com", "cloudflare.com"}}
}

// ReconcileEvent of one name. VPN_DOWN (host "-") says the round could not count VPN failures.
type ReconcileEvent struct {
	Host   string
	Event  string // DIRECT_CONFIRM | DIRECT_FAIL | DIRECT_UNKNOWN | REMOVE | VPN_FAIL | DROP | VPN_DOWN
	Streak int    // direct successes in a row; for VPN_FAIL and DROP - failures of both paths
	Why    string
}

// Reconcile checks the due owned names and returns the ones to take out: REMOVE (opens
// directly again) and DROP (opens through neither path).
func Reconcile(ctx context.Context, o *Owned, p Prober, wanDev string, rc ReconcileConfig, now time.Time) ([]string, []ReconcileEvent) {
	var remove []string
	var ev []ReconcileEvent
	// The VPN's control sites: asked once a round, only when a name needs the answer.
	vpnAsked, vpnWorks := false, false
	vpnOK := func() bool {
		if !vpnAsked {
			vpnAsked = true
			for _, c := range rc.VPNControl {
				if p.Probe(ctx, c, rc.TunnelDev).Verdict == Open {
					vpnWorks = true
					break
				}
			}
			if !vpnWorks {
				ev = append(ev, ReconcileEvent{"-", "VPN_DOWN", 0, "the control sites do not open through the VPN: its failures are not counted"})
			}
		}
		return vpnWorks
	}
	for _, h := range o.Due(now, rc.Every, rc.Batch) {
		n := o.Names[h]
		r := p.Probe(ctx, h, wanDev)
		n.Checked = now
		switch r.Verdict {
		case Open:
			n.VPNFail, n.LastVPNFail = 0, time.Time{}
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
			n.Why = r.Why
			if rc.TunnelDev == "" {
				ev = append(ev, ReconcileEvent{h, "DIRECT_FAIL", 0, r.Why})
				continue
			}
			v := p.Probe(ctx, h, rc.TunnelDev)
			switch {
			case v.Verdict == Open:
				n.VPNFail, n.LastVPNFail = 0, time.Time{}
				ev = append(ev, ReconcileEvent{h, "DIRECT_FAIL", 0, r.Why})
			case v.Verdict == Blocked && vpnOK():
				if !n.LastVPNFail.IsZero() && now.Sub(n.LastVPNFail) < rc.MinGap {
					continue
				}
				n.VPNFail++
				n.LastVPNFail = now
				why := "direct: " + r.Why + "; vpn: " + v.Why
				if n.VPNFail >= rc.Threshold {
					remove = append(remove, h)
					ev = append(ev, ReconcileEvent{h, "DROP", n.VPNFail, why})
				} else {
					ev = append(ev, ReconcileEvent{h, "VPN_FAIL", n.VPNFail, why})
				}
			default:
				// The VPN could not be checked or does not work now: the name stays, nothing counted.
				ev = append(ev, ReconcileEvent{h, "DIRECT_FAIL", 0, r.Why})
			}
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
