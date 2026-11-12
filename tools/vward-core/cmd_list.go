package main

import (
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/journal"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/listops"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/rci"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/router"
)

// vward-core list add|remove|exclude|unexclude|pin LIST DOMAIN | unadapt DOMAIN | clear|delete LIST |
// merge SRC DST | route LIST IFACE|none | retarget FROM TO GROUP...
// The Panel's list operations through the core: one batch, proven, compensated.
// Output: RESULT=changed|unchanged|refused|failed|unknown|blocked, WHY=..., OP=..., MS=...
func listCmd(args []string) {
	fs := flag.NewFlagSet("list", flag.ExitOnError)
	addr := fs.String("rci", "127.0.0.1:79", "RCI address")
	jdir := fs.String("journal", defaultJournal, "journal directory")
	opts := fs.String("options", "auto", "route options (route only)")
	fs.Parse(args)
	a := fs.Args()
	usage := func() {
		fmt.Fprintln(os.Stderr, "usage: vward-core list add|remove|exclude|unexclude|pin LIST DOMAIN | unadapt DOMAIN | clear|delete LIST |\n"+
			"       merge SRC DST | route LIST IFACE|none | retarget FROM TO GROUP...")
		os.Exit(2)
	}
	if len(a) < 2 {
		usage()
	}
	op := listops.Op{Kind: a[0]}
	switch {
	case (a[0] == "add" || a[0] == "remove" || a[0] == "exclude" || a[0] == "unexclude" || a[0] == "pin") && len(a) == 3:
		op.Group, op.Domain = a[1], a[2]
	case a[0] == "unadapt" && len(a) == 2:
		op.Domain = a[1]
	case a[0] == "retarget" && len(a) >= 4:
		op.From, op.Target, op.Groups = a[1], a[2], a[3:]
	case (a[0] == "clear" || a[0] == "delete") && len(a) == 2:
		op.Group = a[1]
	case a[0] == "merge" && len(a) == 3:
		op.Src, op.Group = a[1], a[2]
	case a[0] == "route" && len(a) == 3:
		op.Group = a[1]
		if a[2] == "none" {
			op.NoRoute = true
		} else {
			op.Target, op.Options = a[2], *opts
		}
	default:
		usage()
	}
	t0 := time.Now()
	r := router.New(rci.New(*addr, false), true)
	res, err := listops.Run(r, &journal.Journal{Dir: *jdir}, op, time.Now())
	if err != nil {
		fmt.Printf("RESULT=failed\nWHY=%s\nMS=%s\n", strings.ReplaceAll(err.Error(), "\n", " "), ms(time.Since(t0)))
		os.Exit(1)
	}
	fmt.Printf("RESULT=%s\nOP=%s\nREADS=%d\nBATCHES=%d\nMS=%s\n", res.State, res.Op, res.Reads, res.Batches, ms(time.Since(t0)))
	if res.Why != "" {
		fmt.Printf("WHY=%s\n", strings.ReplaceAll(res.Why, "\n", " "))
	}
	if res.State != "changed" && res.State != "unchanged" {
		os.Exit(1)
	}
}
