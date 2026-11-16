package adaptive

import (
	"bufio"
	"os"
	"strings"
	"time"
)

// Hints: the names of the domain sources - hints-catalog.tsv («domain|source|category»), written
// every night by vward-route-hints-update.sh: itdog, Re:filter and antifilter list sites blocked
// in Russia or refusing it. v2fly is left out: it is a directory of every service's domains
// (Google, Apple, Microsoft…), most of them open directly. The shell engine used the sources and
// the move to Go lost them (owner 16.11.2026): a hinted name is checked directly and through the
// VPN at the same time, and one refusal directly with an answer through the VPN is enough.
// A line without «|» is a name (hints.conf, the tests).
type Hints struct {
	Path string
	mod  time.Time
	size int64
	set  map[string]bool
}

// Reload reads the file when it changed since the last read (or was never read). It says
// whether the set changed; a file that is gone leaves an empty set.
func (h *Hints) Reload() (bool, error) {
	st, err := os.Stat(h.Path)
	if err != nil {
		if os.IsNotExist(err) {
			changed := h.set != nil && len(h.set) > 0
			h.set, h.mod, h.size = map[string]bool{}, time.Time{}, 0
			return changed, nil
		}
		return false, err
	}
	if h.set != nil && st.ModTime().Equal(h.mod) && st.Size() == h.size {
		return false, nil
	}
	f, err := os.Open(h.Path)
	if err != nil {
		return false, err
	}
	defer f.Close()
	set := map[string]bool{}
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 64<<10), 64<<10)
	for sc.Scan() {
		l := strings.TrimSpace(sc.Text())
		if l == "" || l[0] == '#' {
			continue
		}
		if f := strings.Split(l, "|"); len(f) >= 2 {
			if strings.TrimSpace(f[1]) == "v2fly" {
				continue
			}
			l = strings.TrimSpace(f[0])
		}
		l = strings.TrimPrefix(strings.TrimPrefix(l, "*."), ".")
		if n := normalizeName(l); n != "" {
			set[n] = true
		}
	}
	if err := sc.Err(); err != nil {
		return false, err
	}
	h.set, h.mod, h.size = set, st.ModTime(), st.Size()
	return true, nil
}

// Len: the names held.
func (h *Hints) Len() int { return len(h.set) }

// Set: the names held (shared, not to be changed).
func (h *Hints) Set() map[string]bool { return h.set }
