package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/adaptive"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/journal"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/ndm"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/rci"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/router"
)

// eventLog: one line per event, «date|EVENT|host|why», the shell engine's format; the file
// goes to .1 at 512 KiB. Lines are kept in memory and written together (owner 12.11.2026: fewer
// writes to the USB drive): when 64 are waiting, when the oldest waits flushEvery, on flush()
// (the service calls it every few minutes and at stop) and at once for a start, a stop and a
// failure. A power cut loses at most those few minutes of the journal, never a decision.
type eventLog struct {
	mu    sync.Mutex
	path  string
	buf   []string
	since time.Time
	every time.Duration
}

const logBatch = 64

// urgentEvent: written at once (the process may end right after, the owner wants to see it now).
func urgentEvent(event string) bool {
	return event == "START" || event == "STOP" || event == "JOURNAL_BLOCKED" || strings.HasSuffix(event, "_FAILED")
}

func (l *eventLog) flush() {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.flushLocked()
}

func (l *eventLog) flushLocked() {
	if len(l.buf) == 0 {
		return
	}
	if st, err := os.Stat(l.path); err == nil && st.Size() > 512<<10 {
		os.Rename(l.path, l.path+".1")
	}
	f, err := os.OpenFile(l.path, os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0o644)
	if err != nil {
		for _, line := range l.buf {
			fmt.Fprintln(os.Stderr, line)
		}
		l.buf = l.buf[:0]
		return
	}
	f.WriteString(strings.Join(l.buf, "\n") + "\n")
	f.Close()
	l.buf = l.buf[:0]
}

func (l *eventLog) put(event, host, why string) {
	// The zone written out: a static program on the router may not know the local zone, and the
	// Panel's merged journal orders lines by time (a line without a zone is taken as local).
	line := time.Now().Format("2006-01-02T15:04:05-0700") + "|" + event + "|" + host
	if why != "" {
		line += "|" + strings.ReplaceAll(why, "\n", " ")
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.path == "" || l.path == "-" {
		fmt.Println(line)
		return
	}
	if len(l.buf) == 0 {
		l.since = time.Now()
	}
	l.buf = append(l.buf, line)
	every := l.every
	if every <= 0 {
		every = 5 * time.Minute
	}
	if urgentEvent(event) || len(l.buf) >= logBatch || time.Since(l.since) >= every {
		l.flushLocked()
	}
}

type adaptiveFlags struct {
	rciAddr, lan, wan, tunDev, group, jdir, logPath, dns string
	ownedPath, shellPersist                              string
	apply, reconcile                                     bool
	workers, limit                                       int
	batch, saveEvery, refresh, timeout, reconcileTick    time.Duration
}

func parseAdaptive(name string, args []string) (*adaptiveFlags, *flag.FlagSet) {
	f := &adaptiveFlags{}
	fs := flag.NewFlagSet(name, flag.ExitOnError)
	fs.StringVar(&f.rciAddr, "rci", "127.0.0.1:79", "RCI address")
	fs.StringVar(&f.lan, "lan", "br0", "device where the devices' DNS queries are seen")
	fs.StringVar(&f.wan, "wan", "", "the provider's device (empty: the default route's)")
	fs.StringVar(&f.tunDev, "tunnel-dev", "", "the VPN's device (opkgtun4, nwg0...)")
	fs.StringVar(&f.group, "group", "AdaptiveAuto", "the group Keenetic routes to the VPN")
	fs.StringVar(&f.jdir, "journal", defaultJournal, "journal directory")
	fs.StringVar(&f.logPath, "log", "/opt/var/log/vward-core-adaptive.log", "event log (- : stdout)")
	fs.StringVar(&f.dns, "dns", "", "resolver for the checks (empty: the router's)")
	fs.BoolVar(&f.apply, "apply", false, "write into the group (without: observation, nothing sent)")
	fs.BoolVar(&f.reconcile, "reconcile", true, "take names out again once they open directly (3 checks in a row)")
	fs.StringVar(&f.ownedPath, "owned", "/opt/var/lib/vward/core-adaptive/owned.json", "the names Autopodbor added itself")
	fs.StringVar(&f.shellPersist, "shell-persist", "/opt/var/lib/vward/route-engine/adaptive-persist.txt", "the shell engine's list, taken over once")
	fs.IntVar(&f.workers, "workers", 3, "names checked at the same time")
	fs.IntVar(&f.limit, "limit", 290, "names the group may hold (Keenetic keeps 300)")
	fs.DurationVar(&f.batch, "batch", 10*time.Second, "names found within this go as one batch")
	fs.DurationVar(&f.saveEvery, "save-every", 30*time.Minute, "configuration saved at most this often")
	fs.DurationVar(&f.refresh, "refresh", 5*time.Minute, "the router's groups read again this often")
	fs.DurationVar(&f.reconcileTick, "reconcile-tick", 5*time.Minute, "how often the names due for a check are looked at")
	fs.DurationVar(&f.timeout, "timeout", 3*time.Second, "one check (connection, TLS, answer), as the shell engine's 3 s")
	fs.Parse(args)
	if f.wan == "" {
		f.wan = adaptive.DefaultRouteDev()
	}
	return f, fs
}

func checkHost(args []string) {
	f, fs := parseAdaptive("check-host", args)
	if fs.NArg() != 1 || f.tunDev == "" || f.wan == "" {
		fmt.Fprintln(os.Stderr, "usage: vward-core check-host --tunnel-dev DEV [--wan DEV] HOST")
		os.Exit(2)
	}
	r := router.New(rci.New(f.rciAddr, true), true)
	cfg := adaptive.DefaultConfig()
	cfg.Group, cfg.WanDev, cfg.TunnelDev = f.group, f.wan, f.tunDev
	e := adaptive.New(cfg, adaptive.NewProber(f.timeout, f.dns))
	if m, err := r.Read([]string{"groups", "routes", "doh"}); err == nil {
		e.SetConfig(m)
	} else {
		fmt.Printf("ROUTER=UNREAD\tWHY=%v\n", err)
	}
	t0 := time.Now()
	res := e.Check(context.Background(), fs.Arg(0))
	fmt.Printf("HOST=%s\nRESULT=%s\nWHY=%s\nMS=%s\n", res.Host, res.Outcome, res.Why, ms(time.Since(t0)))
}

func runAdaptive(args []string) {
	f, _ := parseAdaptive("adaptive", args)
	if f.tunDev == "" || f.wan == "" {
		fmt.Fprintln(os.Stderr, "adaptive: --tunnel-dev is needed, and --wan when there is no default route")
		os.Exit(2)
	}
	lock, err := os.OpenFile("/tmp/vward-core-adaptive.lock", os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil || syscall.Flock(int(lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB) != nil {
		fmt.Fprintln(os.Stderr, "adaptive: already running")
		os.Exit(1)
	}
	log := &eventLog{path: f.logPath}
	r := router.New(rci.New(f.rciAddr, !f.apply), true)
	j := &journal.Journal{Dir: f.jdir}
	cfg := adaptive.DefaultConfig()
	cfg.Group, cfg.WanDev, cfg.TunnelDev = f.group, f.wan, f.tunDev
	e := adaptive.New(cfg, adaptive.NewProber(f.timeout, f.dns))
	w := &adaptive.Writer{R: r, J: j, Group: f.group, Limit: f.limit, Observe: !f.apply, SaveEvery: f.saveEvery, KeepOps: 50}
	mode := "observe"
	if f.apply {
		mode = "apply"
	}
	log.put("START", "-", fmt.Sprintf("mode=%s lan=%s wan=%s tunnel=%s group=%s", mode, f.lan, f.wan, f.tunDev, f.group))
	if err := j.Gate(); err != nil {
		log.put("JOURNAL_BLOCKED", "-", err.Error()+" (vward-core recover)")
		w.Observe = true
	}
	_, ownedErr := os.Stat(f.ownedPath)
	firstStart := os.IsNotExist(ownedErr)
	owned, err := adaptive.LoadOwned(f.ownedPath)
	if err != nil {
		log.put("OWNED_UNREAD", f.ownedPath, err.Error()+" (starting an empty list)")
	}
	var omu sync.Mutex // owned and the writer: one change at a time
	const ownedEvery = 30 * time.Minute
	ownedSaved := time.Now()
	inGroup := func(m *ndm.Model) map[string]bool {
		out := map[string]bool{}
		if g, ok := m.Groups[f.group]; ok {
			for _, d := range g.Include {
				out[d] = true
			}
		}
		return out
	}
	refresh := func() bool {
		m, err := r.Read([]string{"groups", "routes", "doh"})
		if err != nil {
			log.put("ROUTER_UNREAD", "-", err.Error())
			return false
		}
		e.SetConfig(m)
		omu.Lock()
		if gone := owned.Forget(inGroup(m), time.Now()); len(gone) > 0 {
			for _, h := range gone {
				log.put("OWNER_REMOVED", h, "taken out of "+f.group+" by the owner: not put back for 30 days")
				e.Refuse(h, adaptive.RefuseFor)
			}
			owned.Save()
		}
		omu.Unlock()
		if _, ok := m.Groups[f.group]; !ok || len(m.RoutesOf(f.group)) == 0 {
			log.put("NO_ROUTE", f.group, "the group is missing or not routed to the VPN: nothing is added")
		}
		return true
	}
	for !refresh() {
		time.Sleep(30 * time.Second)
	}
	for h, left := range owned.StillRefused(time.Now()) {
		e.Refuse(h, left)
	}
	if m, err := r.Read([]string{"groups"}); err == nil {
		omu.Lock()
		if n := owned.ImportShell(f.shellPersist, inGroup(m), time.Now()); n > 0 {
			log.put("OWNED_IMPORTED", f.shellPersist, fmt.Sprintf("%d names the shell engine added", n))
			owned.Save()
		}
		// The first start: the names already in the group are rechecked as the shell engine did;
		// the list is saved even when empty, so names added by hand later are never taken.
		if firstStart {
			n := owned.AdoptGroup(inGroup(m), time.Now())
			log.put("OWNED_ADOPTED", f.group, fmt.Sprintf("%d names already in the group, rechecked from now on", n))
			owned.Save()
		}
		omu.Unlock()
	}
	capt, err := adaptive.OpenCapture(f.lan)
	if err != nil {
		log.put("CAPTURE_FAILED", f.lan, err.Error())
		os.Exit(1)
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()

	names := make(chan string, 512)
	go func() {
		buf := make([]byte, 65536)
		recent := map[string]time.Time{}
		last := time.Now()
		for ctx.Err() == nil {
			n, err := capt.Next(buf)
			if err != nil {
				log.put("CAPTURE_FAILED", f.lan, err.Error())
				stop()
				return
			}
			now := time.Now()
			if now.Sub(last) > time.Minute {
				for h, t := range recent {
					if now.Sub(t) > 30*time.Second {
						delete(recent, h)
					}
				}
				last = now
			}
			if n == "" || now.Sub(recent[n]) < 30*time.Second {
				continue
			}
			recent[n] = now
			select {
			case names <- n:
			default: // a burst: the name comes again with its next query
			}
		}
	}()

	var mu sync.Mutex
	pending := map[string]bool{}
	// An hour's summary (owner 12.11.2026): whether Autopodbor works at all is seen in the journal
	// even when nothing changes - names seen, checked, and how the checks ended.
	stats := map[string]int{}
	count := func(k string, n int) { mu.Lock(); stats[k] += n; mu.Unlock() }
	last := map[string]adaptive.Outcome{}
	var wg sync.WaitGroup
	for i := 0; i < f.workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for {
				select {
				case <-ctx.Done():
					return
				case n := <-names:
					res := e.Check(ctx, n)
					count("seen", 1)
					switch res.Outcome {
					case adaptive.Skip, adaptive.Known, adaptive.Cached:
						continue
					}
					mu.Lock()
					stats["checked"]++
					stats[string(res.Outcome)]++
					if last[res.Host] != res.Outcome {
						log.put(string(res.Outcome), res.Host, res.Why)
						last[res.Host] = res.Outcome
					}
					if res.Outcome == adaptive.Add {
						pending[res.Host] = true
					}
					if len(last) > 4096 {
						last = map[string]adaptive.Outcome{}
					}
					mu.Unlock()
				}
			}
		}()
	}

	if f.reconcile {
		rc := adaptive.DefaultReconcile()
		prober := adaptive.NewProber(f.timeout, f.dns)
		wg.Add(1)
		go func() {
			defer wg.Done()
			tick := time.NewTicker(f.reconcileTick)
			defer tick.Stop()
			for {
				select {
				case <-ctx.Done():
					return
				case <-tick.C:
				}
				omu.Lock()
				// The checks themselves run without the lock held for long: a copy of what is due.
				snap := &adaptive.Owned{Names: map[string]*adaptive.Name{}}
				for h, n := range owned.Names {
					c := *n
					snap.Names[h] = &c
				}
				omu.Unlock()
				remove, ev := adaptive.Reconcile(ctx, snap, prober, f.wan, rc, time.Now())
				omu.Lock()
				for h, n := range snap.Names {
					if cur, ok := owned.Names[h]; ok {
						cur.Streak, cur.LastOK, cur.Checked = n.Streak, n.LastOK, n.Checked
					}
				}
				for _, x := range ev {
					if x.Event != "REMOVE" {
						log.put("MAINT_"+x.Event, x.Host, fmt.Sprintf("streak=%d/%d %s", x.Streak, rc.Threshold, x.Why))
					}
				}
				if len(remove) > 0 {
					b, err := w.Remove(remove, time.Now())
					switch {
					case err != nil:
						count("write_failed", 1)
						log.put("REMOVE_FAILED", strings.Join(remove, ","), err.Error())
					case b != nil:
						count("removed", len(b.Removed))
						for _, h := range b.Removed {
							log.put("REMOVED", h, "opened directly 3 times in a row")
							delete(owned.Names, h)
							e.Forget(h)
						}
						for _, h := range b.Would {
							log.put("WOULD_REMOVE", h, "opened directly 3 times in a row")
						}
					}
				}
				// The streaks of the checks are saved at most every ownedEvery (owner 12.11.2026: fewer
				// writes to the USB drive; a power cut only delays a return by a check or two); a
				// removal at once.
				if len(remove) > 0 || time.Since(ownedSaved) >= ownedEvery {
					owned.Save()
					ownedSaved = time.Now()
				}
				omu.Unlock()
				if len(remove) > 0 {
					refresh()
				}
			}
		}()
	}

	batch := time.NewTicker(f.batch)
	defer batch.Stop()
	reread := time.NewTicker(f.refresh)
	defer reread.Stop()
	hourly := time.NewTicker(time.Hour)
	defer hourly.Stop()
	summary := func() {
		mu.Lock()
		s := stats
		stats = map[string]int{}
		mu.Unlock()
		n := 0
		if m, err := r.Read([]string{"groups"}); err == nil && m.Groups[f.group] != nil {
			n = len(m.Groups[f.group].Include)
		}
		omu.Lock()
		owns := len(owned.Names)
		omu.Unlock()
		log.put("STATS", "-", fmt.Sprintf("mode=%s seen=%d checked=%d direct_ok=%d vpn_only=%d vpn_fail=%d unknown=%d isp_unreliable=%d added=%d removed=%d write_failed=%d group=%d/%d own=%d",
			mode, s["seen"], s["checked"], s[string(adaptive.DirectOK)], s[string(adaptive.Add)],
			s[string(adaptive.TunnelFail)]+s[string(adaptive.TunnelUnstable)], s[string(adaptive.ProbeUnknown)],
			s[string(adaptive.ISPUnreliable)], s["added"], s["removed"], s["write_failed"], n, f.limit, owns))
	}
	for {
		select {
		case <-ctx.Done():
			wg.Wait()
			summary()
			omu.Lock()
			defer omu.Unlock()
			if saved, err := w.Flush(time.Now(), true); err != nil {
				log.put("SAVE_FAILED", "-", err.Error())
			} else if saved {
				log.put("SAVED", "-", "at stop")
			}
			if err := owned.Save(); err != nil {
				log.put("OWNED_UNSAVED", f.ownedPath, err.Error())
			}
			log.put("STOP", "-", "")
			log.flush()
			return
		case <-reread.C:
			refresh()
			e.Prune()
			log.flush()
		case <-hourly.C:
			summary()
		case <-batch.C:
			mu.Lock()
			var hosts []string
			for h := range pending {
				hosts = append(hosts, h)
			}
			pending = map[string]bool{}
			mu.Unlock()
			omu.Lock()
			if len(hosts) > 0 {
				b, err := w.Add(hosts, time.Now())
				switch {
				case err != nil:
					count("write_failed", 1)
					log.put("ADD_FAILED", strings.Join(hosts, ","), err.Error())
					for _, h := range hosts {
						e.Forget(h)
					}
				case b != nil:
					count("added", len(b.Added))
					for _, h := range b.Added {
						log.put("ADDED", h, f.group)
						owned.Names[h] = &adaptive.Name{Added: time.Now()}
					}
					if len(b.Added) > 0 {
						if err := owned.Save(); err != nil {
							log.put("OWNED_UNSAVED", f.ownedPath, err.Error())
						}
					}
					for _, h := range b.Would {
						log.put("WOULD_ADD", h, f.group)
					}
					if len(b.Added) == 0 && len(b.Would) == 0 && b.Why != "" {
						log.put("ADD_SKIPPED", strings.Join(hosts, ","), b.Why)
					}
				}
			}
			saved, ferr := w.Flush(time.Now(), false)
			added := len(hosts) > 0
			omu.Unlock()
			if added {
				refresh()
			}
			if ferr != nil {
				log.put("SAVE_FAILED", "-", ferr.Error())
			} else if saved {
				log.put("SAVED", "-", "")
			}
		}
	}
}
