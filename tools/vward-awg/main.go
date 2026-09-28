// vward-awg: one AmneziaWG tunnel (3.x settings included) on a TUN adapter the
// router's own firmware takes as a connection (Keenetic «OpkgTun»).  It is
// amneziawg-go (MIT) as a library plus a reader for the tunnel's .conf file.
//
//	vward-awg -v                       version
//	vward-awg -n -c FILE               check the file, start nothing
//	vward-awg -bench                   encryption speed of this CPU (1 and all threads)
//	... -cpuprofile FILE -profile-after D -profile-for D
//	                                   a CPU profile of the running tunnel (diagnostics)
//	vward-awg -i NAME -c FILE -s STATE run the tunnel on adapter NAME
//
// STATE gets the last handshake time and traffic every few seconds, never a key.
// The router gives the adapter its address and routes; this program only moves
// packets between the adapter and the server.
package main

import (
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"runtime"
	"runtime/pprof"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/amnezia-vpn/amneziawg-go/v3/conn"
	"github.com/amnezia-vpn/amneziawg-go/v3/device"
	"github.com/amnezia-vpn/amneziawg-go/v3/tun"
	"github.com/amnezia-vpn/amneziawg-go/v3/tun/tuntest"
	"golang.org/x/crypto/chacha20poly1305"
)

const version = "1.1.1"

func fail(code int, format string, a ...any) {
	fmt.Fprintf(os.Stderr, "error: "+format+"\n", a...)
	os.Exit(code)
}

func readConf(path string) *Conf {
	f, err := os.Open(path)
	if err != nil {
		fail(1, "the tunnel file cannot be opened")
	}
	defer f.Close()
	c, err := ParseConf(f, nil)
	if err != nil {
		fail(1, "tunnel file: %v", err)
	}
	return c
}

// status: only these fields leave the program's configuration dump.
func status(d *device.Device) (hs, rx, tx int64) {
	s, err := d.IpcGet()
	if err != nil {
		return 0, 0, 0
	}
	for _, l := range strings.Split(s, "\n") {
		k, v, _ := strings.Cut(l, "=")
		n, err := strconv.ParseInt(v, 10, 64)
		if err != nil {
			continue
		}
		switch k {
		case "last_handshake_time_sec":
			if n > hs {
				hs = n
			}
		case "rx_bytes":
			rx += n
		case "tx_bytes":
			tx += n
		}
	}
	return
}

func writeState(path string, d *device.Device) {
	hs, rx, tx := status(d)
	tmp := path + ".tmp"
	body := fmt.Sprintf("handshake=%d\nrx=%d\ntx=%d\npid=%d\nupdated=%d\n", hs, rx, tx, os.Getpid(), time.Now().Unix())
	if os.WriteFile(tmp, []byte(body), 0o644) == nil {
		os.Rename(tmp, path)
	}
}

// bench: how fast this CPU seals and opens tunnel-sized packets, the work every
// packet needs; the tunnel's speed cannot be above it.
func bench(threads int, d time.Duration) float64 {
	var wg sync.WaitGroup
	total := make([]int64, threads)
	stop := time.Now().Add(d)
	for i := 0; i < threads; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			aead, _ := chacha20poly1305.New(make([]byte, chacha20poly1305.KeySize))
			nonce := make([]byte, chacha20poly1305.NonceSize)
			buf := make([]byte, 1420, 1420+aead.Overhead())
			for time.Now().Before(stop) {
				for j := 0; j < 16; j++ {
					sealed := aead.Seal(buf[:0], nonce, buf[:1420], nil)
					if _, err := aead.Open(sealed[:0], nonce, sealed, nil); err != nil {
						panic("bench: open failed")
					}
					total[i] += 1420
				}
			}
		}(i)
	}
	wg.Wait()
	var sum int64
	for _, t := range total {
		sum += t
	}
	return float64(sum) * 8 / d.Seconds() / 1e6
}

// profile: a CPU profile of a window of the tunnel's work (function names only,
// no packet contents or keys), written once and closed.
func profile(path string, after, length time.Duration) {
	time.Sleep(after)
	f, err := os.Create(path)
	if err != nil {
		return
	}
	defer f.Close()
	if pprof.StartCPUProfile(f) != nil {
		return
	}
	time.Sleep(length)
	pprof.StopCPUProfile()
}

func main() {
	showVersion := flag.Bool("v", false, "print the version")
	check := flag.Bool("n", false, "check the tunnel file and exit")
	name := flag.String("i", "", "TUN adapter name")
	confPath := flag.String("c", "", "tunnel .conf file")
	statePath := flag.String("s", "", "state file")
	doBench := flag.Bool("bench", false, "measure the encryption speed of this CPU")
	every := flag.Duration("t", 5*time.Second, "how often the state file is written")
	cpuProfile := flag.String("cpuprofile", "", "write a CPU profile of the running tunnel to this file")
	profAfter := flag.Duration("profile-after", 0, "start the CPU profile this long after the tunnel is up")
	profFor := flag.Duration("profile-for", 15*time.Second, "how long the CPU profile runs")
	flag.Parse()

	if *showVersion {
		fmt.Println("vward-awg " + version)
		return
	}
	if *doBench {
		// Sealing and opening one packet each: a tunnel's traffic in one direction.
		fmt.Printf("encryption, 1 thread: %.1f Mbit/s\n", bench(1, 3*time.Second))
		fmt.Printf("encryption, %d threads: %.1f Mbit/s\n", runtime.NumCPU(), bench(runtime.NumCPU(), 3*time.Second))
		return
	}
	if *confPath == "" {
		fail(64, "usage: vward-awg -n -c FILE | -i NAME -c FILE -s STATE")
	}
	c := readConf(*confPath)
	logger := device.NewLogger(device.LogLevelError, "")

	if *check {
		// The whole configuration goes into a device that has no adapter and sends nothing.
		d := device.NewDevice(tuntest.NewChannelTUN().TUN(), conn.NewDefaultBind(), logger)
		defer d.Close()
		if err := d.IpcSet(c.UAPI); err != nil {
			fail(1, "the tunnel settings are refused: %v", err)
		}
		fmt.Println("ok")
		return
	}
	if *name == "" || *statePath == "" || strings.ContainsAny(*name, "/ ") || len(*name) > 15 {
		fail(64, "usage: vward-awg -i NAME -c FILE -s STATE")
	}
	mtu := c.MTU
	if mtu == 0 {
		mtu = device.DefaultMTU
	}
	tdev, err := tun.CreateTUN(*name, mtu)
	if err != nil {
		fail(2, "adapter %s cannot be created: %v", *name, err)
	}
	logger = device.NewLogger(device.LogLevelError, "("+*name+") ")
	d := device.NewDevice(tdev, conn.NewDefaultBind(), logger)
	if err := d.IpcSet(c.UAPI); err != nil {
		d.Close()
		fail(1, "the tunnel settings are refused: %v", err)
	}
	if err := d.Up(); err != nil {
		d.Close()
		fail(2, "the tunnel cannot start: %v", err)
	}
	os.MkdirAll(filepath.Dir(*statePath), 0o755)
	writeState(*statePath, d)
	if *cpuProfile != "" {
		go profile(*cpuProfile, *profAfter, *profFor)
	}

	term := make(chan os.Signal, 1)
	signal.Notify(term, syscall.SIGTERM, os.Interrupt, syscall.SIGHUP)
	tick := time.NewTicker(*every)
	defer tick.Stop()
	for {
		select {
		case <-tick.C:
			writeState(*statePath, d)
		case <-term:
			d.Close()
			os.Remove(*statePath)
			return
		case <-d.Wait():
			os.Remove(*statePath)
			fail(2, "the tunnel stopped")
		}
	}
}
