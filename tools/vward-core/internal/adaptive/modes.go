package adaptive

import (
	"os"
	"path/filepath"
	"strings"
)

// Modes: what the owner's switches say now. Read from the settings directory every few seconds
// while Autopodbor runs (fix.39): a switch in the Panel acts at once, not at the next restart -
// Autopodbor switched off kept adding names until the router restarted it.
type Modes struct {
	Observe  bool // nothing is written: Autopodbor is switched off (adaptive.disabled) or core.observe
	VPNCheck Mode // the VPN check of the names that do not open directly (adaptive.vpncheck)
}

// ReadModes of dir (/opt/etc/vward/route-engine); "" - no directory given: write, the sandbox.
// A file that cannot be asked about (no permission, a broken drive) counts as «do not write».
// The VPN check without a file or with an unknown word is in the sandbox: it changes nothing.
func ReadModes(dir string) Modes {
	m := Modes{VPNCheck: ModeSandbox}
	if dir == "" {
		return m
	}
	for _, f := range []string{"adaptive.disabled", "core.observe"} {
		if _, err := os.Stat(filepath.Join(dir, f)); err == nil || !os.IsNotExist(err) {
			m.Observe = true
		}
	}
	if b, err := os.ReadFile(filepath.Join(dir, "adaptive.vpncheck")); err == nil {
		switch Mode(strings.TrimSpace(string(b))) {
		case ModeOff:
			m.VPNCheck = ModeOff
		case ModeOn:
			m.VPNCheck = ModeOn
		}
	}
	return m
}
