package adaptive

import (
	"context"
	"time"
)

// Taking names out of the group again, the route reconciler's rule: a name Autopodbor added is
// checked directly now and then; it leaves the group after 3 direct checks in a row that
// opened, at least 4 minutes apart. A failed check or one that could not tell starts over.
//
// The VPN check (fix.39, owner's journal 12.11.2026): a name that does not open directly is
// checked through the VPN too. One that opens neither way Threshold rounds in a row, the VPN
// itself working (a control site opens through it), has no reason to be in the group: addresses
// with no HTTPS at all stayed in the VPN for good (2.datadog.pool.ntp.org, ftp.lug.ro,
// tracker.opentrackr.org). A rule of Autopodbor itself, not a new part: it works at once, with
// no sandbox (owner 14.11.2026).

type ReconcileConfig struct {
	Every     time.Duration // a name is checked again after this
	Batch     int           // names checked per round
	Threshold int           // direct checks in a row before removal
	MinGap    time.Duration // between two counted checks

	TunnelDev  string   // the VPN's device ("" - no VPN check)
	VPNControl []string // sites that must open through the VPN for a VPN failure to count
}

func DefaultReconcile() ReconcileConfig {
	return ReconcileConfig{Every: 30 * time.Minute, Batch: 8, Threshold: 3, MinGap: 4 * time.Minute,
		VPNControl: []string{"www.google.com", "www.cloudflare.com"}}
}

// ReconcileEvent of one name.
type ReconcileEvent struct {
	Host string
	// DIRECT_CONFIRM | DIRECT_FAIL | DIRECT_UNKNOWN | REMOVE | VPN_FAIL (opens neither way, counted) |
	// VPN_UNRELIABLE (the VPN itself does not open the control sites: nothing counted this round;
	// Host "-").
	Event  string
	Streak int
	Why    string
}

// Reconcile checks the due owned names and returns the ones to take out (Streak reached).
func Reconcile(ctx context.Context, o *Owned, p Prober, wanDev string, rc ReconcileConfig, now time.Time) ([]string, []ReconcileEvent) {
	var remove []string
	var ev []ReconcileEvent
	vpnCheck := rc.TunnelDev != ""
	vpnWorks := Unknown // asked once a round, when the first name fails through the VPN
	for _, h := range o.Due(now, rc.Every, rc.Batch) {
		n := o.Names[h]
		r := p.Probe(ctx, h, wanDev)
		n.Checked = now
		switch r.Verdict {
		case Open:
			n.VPNFail, n.LastVPNFail, n.Why = 0, time.Time{}, ""
			if !n.LastOK.IsZero() && now.Sub(n.LastOK) < rc.MinGap {
				continue
			}
			n.Streak++
			n.LastOK = now
			if n.Streak >= rc.Threshold {
				remove = append(remove, h)
				ev = append(ev, ReconcileEvent{h, "REMOVE", n.Streak, "opened directly " + itoa(n.Streak) + " times in a row"})
			} else {
				ev = append(ev, ReconcileEvent{h, "DIRECT_CONFIRM", n.Streak, r.Why})
			}
		case Blocked:
			n.Streak, n.LastOK = 0, time.Time{}
			n.Why = r.Why
			if !vpnCheck {
				ev = append(ev, ReconcileEvent{h, "DIRECT_FAIL", 0, r.Why})
				continue
			}
			v := p.Probe(ctx, h, rc.TunnelDev)
			if v.Verdict != Blocked {
				// It opens through the VPN (its place is in the group), or the check could not tell.
				if v.Verdict == Open {
					n.VPNFail, n.LastVPNFail = 0, time.Time{}
				}
				ev = append(ev, ReconcileEvent{h, "DIRECT_FAIL", 0, r.Why})
				continue
			}
			if vpnWorks == Unknown {
				vpnWorks = Blocked
				for _, c := range rc.VPNControl {
					if p.Probe(ctx, c, rc.TunnelDev).Verdict == Open {
						vpnWorks = Open
						break
					}
				}
				if vpnWorks != Open {
					ev = append(ev, ReconcileEvent{"-", "VPN_UNRELIABLE", 0, "the control sites do not open through the VPN: nothing is counted"})
				}
			}
			if vpnWorks != Open {
				ev = append(ev, ReconcileEvent{h, "DIRECT_FAIL", 0, r.Why})
				continue
			}
			why := "direct: " + r.Why + "; vpn: " + v.Why
			if n.LastVPNFail.IsZero() || now.Sub(n.LastVPNFail) >= rc.MinGap {
				n.VPNFail++
				n.LastVPNFail = now
				if n.VPNFail < rc.Threshold {
					ev = append(ev, ReconcileEvent{h, "VPN_FAIL", n.VPNFail, why})
					continue
				}
				remove = append(remove, h)
				ev = append(ev, ReconcileEvent{h, "REMOVE", n.VPNFail, "does not open through the VPN either (" + why + ")"})
				continue
			}
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

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	var b [20]byte
	i := len(b)
	for ; n > 0; n /= 10 {
		i--
		b[i] = byte('0' + n%10)
	}
	return string(b[i:])
}
