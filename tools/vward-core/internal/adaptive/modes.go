package adaptive

import (
	"os"
	"path/filepath"
)

// Modes: what the owner's switches say now. Read from the settings directory every few seconds
// while Autopodbor runs (fix.39): a switch in the Panel acts at once, not at the next restart -
// Autopodbor switched off kept adding names until the router restarted it.
type Modes struct {
	Observe bool // nothing is written: Autopodbor is switched off (adaptive.disabled) or core.observe
}

// ReadModes of dir (/opt/etc/vward/route-engine); "" - no directory given: write.
// A file that cannot be asked about (no permission, a broken drive) counts as «do not write».
func ReadModes(dir string) Modes {
	var m Modes
	if dir == "" {
		return m
	}
	for _, f := range []string{"adaptive.disabled", "core.observe"} {
		if _, err := os.Stat(filepath.Join(dir, f)); err == nil || !os.IsNotExist(err) {
			m.Observe = true
		}
	}
	return m
}
