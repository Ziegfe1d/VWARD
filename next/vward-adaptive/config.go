package main

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// Config is /opt/etc/vward-adaptive.conf: key=value lines, # comments.
type Config struct {
	Mode         string // observe: only logs what it would do; apply: writes to Keenetic
	Group        string // Keenetic «object-group fqdn» the program adds to
	LanDev       string // where the devices' DNS queries are seen
	WanDev       string // direct path; empty: the default route's device
	TunnelDev    string // kernel device of the VPN (opkgtun4, nwg0...)
	DNS          string // resolver host:port for probes; empty: /etc/resolv.conf
	RCI          string
	MaxEntries   int
	ExpireDays   int
	Recheck      time.Duration
	ProbeTimeout time.Duration
	CollapseAt   int // own hosts under one base domain before the base domain replaces them
	Ignore       []string
	Log          string
	State        string
}

func defaultConfig() Config {
	return Config{
		Mode: "observe", Group: "AdaptiveAuto", LanDev: "br0", RCI: "127.0.0.1:79",
		MaxEntries: 280, ExpireDays: 30, Recheck: 6 * time.Hour, ProbeTimeout: 6 * time.Second,
		CollapseAt: 3,
		Log:        "/opt/var/log/vward-adaptive.log",
		State:      "/opt/var/lib/vward-adaptive/state.json",
	}
}

func loadConfig(path string) (Config, error) {
	c := defaultConfig()
	f, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			return c, c.validate()
		}
		return c, err
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	n := 0
	for sc.Scan() {
		n++
		line := strings.TrimSpace(sc.Text())
		if i := strings.IndexByte(line, '#'); i >= 0 {
			line = strings.TrimSpace(line[:i])
		}
		if line == "" {
			continue
		}
		k, v, ok := strings.Cut(line, "=")
		if !ok {
			return c, fmt.Errorf("%s:%d: no '='", path, n)
		}
		k, v = strings.TrimSpace(k), strings.Trim(strings.TrimSpace(v), `"'`)
		if err := c.set(k, v); err != nil {
			return c, fmt.Errorf("%s:%d: %v", path, n, err)
		}
	}
	if err := sc.Err(); err != nil {
		return c, err
	}
	return c, c.validate()
}

func (c *Config) set(k, v string) error {
	num := func() (int, error) {
		n, err := strconv.Atoi(v)
		if err != nil || n < 0 {
			return 0, fmt.Errorf("%s: not a number: %q", k, v)
		}
		return n, nil
	}
	var err error
	var n int
	switch k {
	case "mode":
		c.Mode = v
	case "group":
		c.Group = v
	case "lan_dev":
		c.LanDev = v
	case "wan_dev":
		c.WanDev = v
	case "tunnel_dev":
		c.TunnelDev = v
	case "dns":
		c.DNS = v
	case "rci":
		c.RCI = v
	case "max_entries":
		c.MaxEntries, err = num()
	case "expire_days":
		c.ExpireDays, err = num()
	case "recheck_hours":
		n, err = num()
		c.Recheck = time.Duration(n) * time.Hour
	case "probe_timeout_sec":
		n, err = num()
		c.ProbeTimeout = time.Duration(n) * time.Second
	case "collapse_at":
		c.CollapseAt, err = num()
	case "ignore":
		c.Ignore = nil
		for _, d := range strings.Fields(strings.ReplaceAll(v, ",", " ")) {
			if d = normalizeName(d); d != "" {
				c.Ignore = append(c.Ignore, d)
			}
		}
	case "log":
		c.Log = v
	case "state":
		c.State = v
	default:
		return fmt.Errorf("unknown key %q", k)
	}
	return err
}

func (c *Config) validate() error {
	if c.Mode != "observe" && c.Mode != "apply" {
		return fmt.Errorf("mode must be observe or apply, not %q", c.Mode)
	}
	if !validGroupName(c.Group) {
		return fmt.Errorf("bad group name %q", c.Group)
	}
	for _, d := range []struct{ k, v string }{{"lan_dev", c.LanDev}, {"wan_dev", c.WanDev}, {"tunnel_dev", c.TunnelDev}} {
		if d.v != "" && !validDev(d.v) {
			return fmt.Errorf("bad %s %q", d.k, d.v)
		}
	}
	if c.LanDev == "" {
		return fmt.Errorf("lan_dev is empty")
	}
	if c.MaxEntries < 1 || c.MaxEntries > 300 {
		return fmt.Errorf("max_entries must be 1..300 (Keenetic keeps 300 names in a group)")
	}
	if c.ProbeTimeout < time.Second {
		c.ProbeTimeout = time.Second
	}
	if c.Recheck < time.Hour {
		c.Recheck = time.Hour
	}
	return nil
}

func validGroupName(s string) bool {
	if s == "" || len(s) > 32 {
		return false
	}
	for _, r := range s {
		if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '_' || r == '-') {
			return false
		}
	}
	return true
}

func validDev(s string) bool {
	if len(s) == 0 || len(s) > 15 {
		return false
	}
	for _, r := range s {
		if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '.' || r == '_' || r == '-') {
			return false
		}
	}
	return true
}
