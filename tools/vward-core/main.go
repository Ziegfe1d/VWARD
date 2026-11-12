// vward-core: VWARD's routing core in Go (owner 08.11; write path 11.11.2026). Writes to the
// router: selftest --yes (its own test group), adaptive --apply (names into AdaptiveAuto) and
// list (the owner's lists, asked for in the Panel);
// recover writes only the local journal. Everything else only reads (RCI GET, «show» parse) and prints to stdout.
//
//	vward-core version
//	vward-core probe    [--rci 127.0.0.1:79]           time of RCI reads, narrow and full
//	vward-core dry-run  [--rci ...] [--etc /opt/etc/vward] [--full]
//	                     the plan the core WOULD send for the saved service choices; nothing sent
//	vward-core selftest [--rci ...] [--journal DIR] [--tunnel NAME] [--backup DIR] [--yes]
//	                     the first write on the router: the group VwardTest created, proven,
//	                     removed, proven; without --yes only the plan
//	vward-core recover  [--rci ...] [--journal DIR] [--yes]
//	                     operations a crash left open, closed by a read of the router (no replay)
//	vward-core adaptive --tunnel-dev DEV [--lan br0] [--wan DEV] [--group AdaptiveAuto] [--apply] ...
//	                     Autopodbor: DNS queries on the LAN, checks direct and through the VPN,
//	                     names that open only through the VPN into the group (observation
//	                     without --apply: nothing sent)
//	vward-core check-host --tunnel-dev DEV [--wan DEV] HOST
//	                     one name checked the same way; nothing sent
//	vward-core list add|remove LIST DOMAIN | clear|delete LIST | merge SRC DST | route LIST IFACE|none
//	                     the Panel's list operations: one batch, proven, compensated
package main

import (
	"bufio"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/ndm"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/own"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/plan"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/rci"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/router"
)

var version = "proto-4"

func main() {
	if len(os.Args) < 2 {
		usage()
	}
	switch os.Args[1] {
	case "version":
		fmt.Printf("vward-core %s %s/%s write=selftest,adaptive,list\n", version, runtime.GOOS, runtime.GOARCH)
	case "probe":
		probe(os.Args[2:])
	case "dry-run":
		dryRun(os.Args[2:])
	case "selftest":
		selfTest(os.Args[2:])
	case "recover":
		recoverOpen(os.Args[2:])
	case "adaptive":
		runAdaptive(os.Args[2:])
	case "check-host":
		checkHost(os.Args[2:])
	case "list":
		listCmd(os.Args[2:])
	default:
		usage()
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, "usage: vward-core version | probe [--rci ADDR] | dry-run [--rci ADDR] [--etc DIR] [--full]\n"+
		"       | selftest [--rci ADDR] [--journal DIR] [--tunnel NAME] [--backup DIR] [--yes] | recover [--rci ADDR] [--journal DIR] [--yes]\n"+
		"       | adaptive --tunnel-dev DEV [--lan br0] [--wan DEV] [--group AdaptiveAuto] [--apply] | check-host --tunnel-dev DEV [--wan DEV] HOST\n"+
		"       | list add|remove LIST DOMAIN | clear|delete LIST | merge SRC DST | route LIST IFACE|none")
	os.Exit(2)
}

func ms(d time.Duration) string { return fmt.Sprintf("%d", d.Milliseconds()) }

// rss: the peak resident memory of this process (VmHWM), KiB.
func rss() string {
	f, err := os.Open("/proc/self/status")
	if err != nil {
		return "?"
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		if strings.HasPrefix(sc.Text(), "VmHWM:") {
			return strings.TrimSpace(strings.TrimPrefix(sc.Text(), "VmHWM:"))
		}
	}
	return "?"
}

func probe(args []string) {
	fs := flag.NewFlagSet("probe", flag.ExitOnError)
	addr := fs.String("rci", "127.0.0.1:79", "RCI address")
	fs.Parse(args)
	c := rci.New(*addr, true)
	fmt.Println("RCI_PROBE=read-only")
	fmt.Println("endpoint\tok\tms\tbytes\tshape")
	paths := []string{"show/version", "show/running-config", "object-group/fqdn", "dns-proxy", "dns-proxy/route",
		"ip/route", "ip/name-server", "show/object-group/fqdn", "show/interface", "show/internet/status", "show/ip/hotspot"}
	for _, p := range paths {
		t0 := time.Now()
		b, err := c.Get(p)
		d := time.Since(t0)
		ok := "yes"
		if err != nil {
			ok = "no:" + strings.ReplaceAll(err.Error(), "\t", " ")
		}
		fmt.Printf("%s\t%s\t%s\t%d\t%s\n", p, ok, ms(d), len(b), ndm.Shape(b, 3))
	}
	// One «show» through the batch form (the form every write would use).
	t0 := time.Now()
	res, err := c.Parse([]string{"show version"})
	st := "ok"
	if err != nil {
		st = "no:" + err.Error()
	} else if len(res) == 1 && res[0].Status == "error" {
		st = "error:" + res[0].Message
	}
	fmt.Printf("POST parse[show version]\t%s\t%s\t-\t-\n", st, ms(time.Since(t0)))
	// The same full read through ndmc, the way the shell core does it.
	if p, err := exec.LookPath("ndmc"); err == nil {
		t0 := time.Now()
		out, err := exec.Command(p, "-c", "show running-config").Output()
		ok := "yes"
		if err != nil {
			ok = "no"
		}
		fmt.Printf("ndmc show running-config\t%s\t%s\t%d\t-\n", ok, ms(time.Since(t0)), len(out))
	}
	fmt.Printf("RCI_CALLS=%d RCI_BYTES=%d RSS_PEAK=%s\n", c.Calls.Load(), c.Bytes.Load(), rss())
}

type service struct{ id, group, pin string }

func readServices(etc string) ([]service, error) {
	f, err := os.Open(filepath.Join(etc, "services/enabled.tsv"))
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	defer f.Close()
	var out []service
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		p := strings.Split(sc.Text(), "\t")
		if len(p) == 3 {
			out = append(out, service{p[0], p[1], p[2]})
		}
	}
	return out, sc.Err()
}

func deviceTunnel(etc string) string {
	b, err := os.ReadFile(filepath.Join(etc, "device.conf"))
	if err != nil {
		return ""
	}
	for _, l := range strings.Split(string(b), "\n") {
		if v, ok := strings.CutPrefix(l, "VWARD_TUNNEL_INTERFACE="); ok {
			return strings.Trim(v, `"' `)
		}
	}
	return ""
}

func compare(a, b *ndm.Model, area string) (bool, string) {
	var x, y []string
	switch area {
	case "groups":
		for _, n := range a.GroupOrder {
			x = append(x, n+"="+a.Fingerprint("group:"+n))
		}
		for _, n := range b.GroupOrder {
			y = append(y, n+"="+b.Fingerprint("group:"+n))
		}
	case "routes":
		for _, r := range a.Routes {
			x = append(x, r.Group+" "+r.Target+" "+r.Options)
		}
		for _, r := range b.Routes {
			y = append(y, r.Group+" "+r.Target+" "+r.Options)
		}
	case "doh":
		x, y = strings.Split(a.Fingerprint("doh"), "\n"), strings.Split(b.Fingerprint("doh"), "\n")
	}
	sort.Strings(x)
	sort.Strings(y)
	if strings.Join(x, "\n") == strings.Join(y, "\n") {
		return true, fmt.Sprintf("%d items", len(x))
	}
	return false, fmt.Sprintf("full %d items, narrow %d items", len(x), len(y))
}

func dryRun(args []string) {
	fs := flag.NewFlagSet("dry-run", flag.ExitOnError)
	addr := fs.String("rci", "127.0.0.1:79", "RCI address")
	etc := fs.String("etc", "/opt/etc/vward", "VWARD settings (read only)")
	backup := fs.String("backup", "/opt/var/backups/vward/console-config", "the shell core's transaction journal (read only)")
	full := fs.Bool("full", false, "plan from the full read even when the narrow one matches")
	fs.Parse(args)
	start := time.Now()
	c := rci.New(*addr, true)
	fmt.Println("DRY_RUN=read-only (nothing is sent to the router, no file is written)")

	r := router.New(c, false)
	t0 := time.Now()
	fullModel, _, err := r.Full()
	tFull := time.Since(t0)
	if err != nil {
		fmt.Printf("FULL_READ=fail %v\n", err)
		os.Exit(1)
	}
	fmt.Printf("FULL_READ=ok ms=%s groups=%d routes=%d doh=%d ip_routes=%d name_servers=%d\n", ms(tFull),
		len(fullModel.Groups), len(fullModel.Routes), len(fullModel.DoH), len(fullModel.IPRoutes), len(fullModel.NameServers))

	rn := router.New(c, true)
	t0 = time.Now()
	narrow, nerr := rn.Read([]string{"groups", "routes", "doh"})
	tNarrow := time.Since(t0)
	narrowOK := nerr == nil
	if nerr != nil {
		fmt.Printf("NARROW_READ=fail ms=%s %v\n", ms(tNarrow), nerr)
	} else {
		fmt.Printf("NARROW_READ=ok ms=%s (groups %s ms, dns-proxy %s ms)\n", ms(tNarrow), ms(rn.Timing["narrow:groups"]), ms(rn.Timing["narrow:dns-proxy"]))
		for _, a := range []string{"groups", "routes", "doh"} {
			eq, why := compare(fullModel, narrow, a)
			if !eq {
				narrowOK = false
			}
			fmt.Printf("NARROW_EQUALS_FULL %s=%v %s\n", a, eq, why)
		}
	}
	base := fullModel
	if narrowOK && !*full {
		base = narrow
	}

	// Protected objects: counted for the report; the core never writes them whatever is found
	// (allowlist of command forms on VWARD's own objects, plan.Check).
	g8, ns16 := 0, 0
	for _, x := range fullModel.IPRoutes {
		if x.Target == "OpkgTun4" {
			g8++
		}
	}
	for _, x := range fullModel.NameServers {
		if x.Iface == "OpkgTun4" {
			ns16++
		}
	}
	fmt.Printf("PROTECTED ip_route_OpkgTun4=%d name_server_OpkgTun4=%d dns_proxy_other_lines=%d\n",
		g8, ns16, len(fullModel.DNSOther))
	fmt.Println("PROTECTION=allowlist (only VWARD's groups, their routes and VWARD's Smart DNS rows; no write into dns-proxy filter/profiles)")

	// Desired image of the owned service groups from the saved choices (enabled.tsv):
	// includes as they are, one route to the pinned tunnel («auto» = the default tunnel).
	svcs, err := readServices(*etc)
	if err != nil {
		fmt.Printf("SERVICES=unreadable %v\n", err)
	}
	def := deviceTunnel(*etc)
	want := plan.Desired{OwnedGroups: map[string]bool{}}
	nOwned := 0
	want.RouteGroups = map[string]bool{}
	op := own.Paths{Etc: *etc, Backup: *backup}
	levels := map[string]int{}
	for _, s := range svcs {
		v := own.Service(op, fullModel, s.id, s.group, s.pin, def)
		levels[v.Level.String()]++
		fmt.Printf("SERVICE %s group=%s pin=%s ownership=%s (%s)\n", s.id, s.group, s.pin, v.Level, v.Reason)
		g := base.Groups[s.group]
		if g == nil || v.Level == own.None {
			continue
		}
		t := s.pin
		if t == "auto" {
			t = def
		}
		if v.Level == own.Full {
			nOwned++
			want.OwnedGroups[s.group] = true
		} else {
			want.RouteGroups[s.group] = true
		}
		want.Groups = append(want.Groups, plan.Group{Name: s.group, Include: append([]string(nil), g.Include...), Target: t, Options: "auto"})
	}
	fmt.Printf("OWNERSHIP full=%d route=%d none=%d\n", levels["full"], levels["route"], levels["none"])
	t0 = time.Now()
	p, err := plan.Build(base, want, nil)
	tPlan := time.Since(t0)
	if err != nil {
		fmt.Printf("PLAN=refused %v\n", err)
	} else {
		fmt.Printf("PLAN=ok ms=%s services=%d owned=%d commands=%d refused=%d\n", ms(tPlan), len(svcs), nOwned, len(p.Steps), len(p.Refused))
		for _, s := range p.Steps {
			fmt.Printf("WOULD_SEND %s\n", s.Cmd)
		}
		for _, x := range p.Refused {
			fmt.Printf("WOULD_REFUSE %s\n", x)
		}
	}
	// The CPU part of one switch on this processor, offline: a synthetic service of 175
	// domains planned and its expected image computed (nothing is sent; the group name is
	// one no router has).
	t0 = time.Now()
	sim := plan.Group{Name: "vward-dryrun-probe-0", Target: def, Options: "auto"}
	if sim.Target == "" {
		sim.Target = "Wireguard0"
	}
	for i := 0; i < 175; i++ {
		sim.Include = append(sim.Include, fmt.Sprintf("d%03d.dryrun.invalid", i))
	}
	simOwned := map[string]bool{sim.Name: true}
	for k := range want.OwnedGroups {
		simOwned[k] = true
	}
	sp, err := plan.Build(base, plan.Desired{Groups: append(want.Groups, sim), OwnedGroups: simOwned}, nil)
	if err == nil {
		exp := base.Clone()
		for _, s := range sp.Steps {
			exp.Apply(s.Cmd)
		}
		_ = exp.Fingerprint("group:" + sim.Name)
		fmt.Printf("SIMULATED_SWITCH_CPU_MS=%s commands=%d (175 domains: plan + expected image, not sent)\n", ms(time.Since(t0)), len(sp.Steps))
	}
	// What one switch would cost: CAS read + batch + read after (narrow, measured above).
	per := tNarrow
	if !narrowOK {
		per = tFull
	}
	fmt.Printf("ESTIMATE_SWITCH_MS=%d (read before + one batch + read after; batch not measured: nothing is sent)\n", (2*per + tPlan).Milliseconds())
	fmt.Printf("TOTAL_MS=%s RCI_CALLS=%d RCI_BYTES=%d RSS_PEAK=%s\n", ms(time.Since(start)), c.Calls.Load(), c.Bytes.Load(), rss())
}
