// vward-awg: one AmneziaWG tunnel (3.x settings included) on a TUN adapter the
// router's own firmware takes as a connection (Keenetic «OpkgTun»).  It is
// amneziawg-go (MIT) as a library plus a reader for the tunnel's .conf file.
//
//	vward-awg -v                       version
//	vward-awg -n -c FILE               check the file, start nothing
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
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/amnezia-vpn/amneziawg-go/v3/conn"
	"github.com/amnezia-vpn/amneziawg-go/v3/device"
	"github.com/amnezia-vpn/amneziawg-go/v3/tun"
	"github.com/amnezia-vpn/amneziawg-go/v3/tun/tuntest"
)

const version = "1.0.0"

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

func main() {
	showVersion := flag.Bool("v", false, "print the version")
	check := flag.Bool("n", false, "check the tunnel file and exit")
	name := flag.String("i", "", "TUN adapter name")
	confPath := flag.String("c", "", "tunnel .conf file")
	statePath := flag.String("s", "", "state file")
	every := flag.Duration("t", 5*time.Second, "how often the state file is written")
	flag.Parse()

	if *showVersion {
		fmt.Println("vward-awg " + version)
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
