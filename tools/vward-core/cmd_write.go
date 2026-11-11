package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/journal"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/ndm"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/rci"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/recovery"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/router"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/selftest"
)

const defaultJournal = "/opt/var/lib/vward/core-journal"

func selfTest(args []string) {
	fs := flag.NewFlagSet("selftest", flag.ExitOnError)
	addr := fs.String("rci", "127.0.0.1:79", "RCI address")
	jdir := fs.String("journal", defaultJournal, "journal directory")
	tunnel := fs.String("tunnel", "", "Keenetic interface for the test route (empty: the group alone)")
	backup := fs.String("backup", "/opt/var/backups/vward", "where the configuration copy goes before writing")
	yes := fs.Bool("yes", false, "send it (without: the plan only)")
	fs.Parse(args)
	c := rci.New(*addr, !*yes)
	r := router.New(c, true)
	j := &journal.Journal{Dir: *jdir}
	if *yes {
		// A copy of the whole configuration first: the record of the router before the test.
		b, err := c.Get("show/running-config")
		if err != nil {
			fmt.Printf("SELFTEST=STOP\nWHY=configuration not read for the copy: %v\n", err)
			os.Exit(1)
		}
		text, err := ndm.RunningFromRCI(b)
		if err != nil {
			fmt.Printf("SELFTEST=STOP\nWHY=configuration copy: %v\n", err)
			os.Exit(1)
		}
		copyPath := filepath.Join(*backup, fmt.Sprintf("core-selftest-%s.running-config", time.Now().Format("20060102-150405")))
		if err := os.MkdirAll(*backup, 0o700); err == nil {
			err = os.WriteFile(copyPath, []byte(text), 0o600)
		}
		if err != nil {
			fmt.Printf("SELFTEST=STOP\nWHY=configuration copy not written: %v\n", err)
			os.Exit(1)
		}
		fmt.Printf("COPY=%s\n", copyPath)
	}
	t0 := time.Now()
	rep, err := selftest.Run(r, j, *tunnel, time.Now(), *yes)
	if err != nil {
		fmt.Printf("SELFTEST=STOP\nWHY=%v\n", err)
		os.Exit(1)
	}
	for _, s := range rep.Steps {
		fmt.Printf("STEP=%s\top=%s\tstate=%s\treads=%d\tbatches=%d\tms=%s\n", s.Name, s.Op, s.Outcome.State, s.Reads, s.Batches, ms(s.Took))
		for _, c := range s.Commands {
			fmt.Printf("  %s\n", c)
		}
	}
	fmt.Printf("TOTAL_MS=%s\nRSS_PEAK=%s\n", ms(time.Since(t0)), rss())
	if !rep.OK {
		fmt.Printf("SELFTEST=FAIL\nWHY=%s\n", rep.Why)
		os.Exit(1)
	}
	fmt.Printf("SELFTEST=PASS\nWHY=%s\n", rep.Why)
}

func recoverOpen(args []string) {
	fs := flag.NewFlagSet("recover", flag.ExitOnError)
	addr := fs.String("rci", "127.0.0.1:79", "RCI address")
	jdir := fs.String("journal", defaultJournal, "journal directory")
	yes := fs.Bool("yes", false, "write the resolution into the journal (without: a report only)")
	fs.Parse(args)
	r := router.New(rci.New(*addr, true), true)
	reps, err := recovery.Run(r, &journal.Journal{Dir: *jdir}, *yes)
	for _, x := range reps {
		fmt.Printf("OP=%s\twas=%s\tnow=%s\twhy=%s\n", x.Op, x.Was, x.Now, x.Why)
	}
	if err != nil {
		fmt.Printf("RECOVER=FAIL\nWHY=%v\n", err)
		os.Exit(1)
	}
	open := 0
	for _, x := range reps {
		if x.Now == "open" {
			open++
		}
	}
	fmt.Printf("RECOVER=%s\nOPEN=%d\n", map[bool]string{true: "OK", false: "OPEN"}[open == 0], open)
	if open > 0 {
		os.Exit(1)
	}
}
