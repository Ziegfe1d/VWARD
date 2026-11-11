package adaptive

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// Owned: the names Autopodbor itself put into the group. Only these are ever taken out again
// (the shell engine kept the same list in adaptive-persist.txt; it is taken over once). A name
// the owner adds by hand is not here and is never removed.
type Owned struct {
	Path  string `json:"-"`
	Names map[string]*Name `json:"names"`
}

type Name struct {
	Added   time.Time `json:"added"`
	Streak  int       `json:"streak"`            // direct checks in a row that opened
	LastOK  time.Time `json:"last_ok,omitempty"` // the last of them
	Checked time.Time `json:"checked,omitempty"` // the last check of any result
}

func LoadOwned(path string) (*Owned, error) {
	o := &Owned{Path: path, Names: map[string]*Name{}}
	b, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return o, nil
	}
	if err != nil {
		return o, err
	}
	if err := json.Unmarshal(b, o); err != nil {
		return &Owned{Path: path, Names: map[string]*Name{}}, err
	}
	o.Path = path
	if o.Names == nil {
		o.Names = map[string]*Name{}
	}
	return o, nil
}

// ImportShell takes over the shell engine's list (one name a line): names still in the group.
func (o *Owned) ImportShell(path string, inGroup map[string]bool, now time.Time) int {
	f, err := os.Open(path)
	if err != nil {
		return 0
	}
	defer f.Close()
	n := 0
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		h := normalizeName(strings.TrimSpace(sc.Text()))
		if h == "" || !inGroup[h] || o.Names[h] != nil {
			continue
		}
		o.Names[h] = &Name{Added: now}
		n++
	}
	return n
}

// Save atomically (a cut power never leaves half a file).
func (o *Owned) Save() error {
	if err := os.MkdirAll(filepath.Dir(o.Path), 0o700); err != nil {
		return err
	}
	b, _ := json.MarshalIndent(o, "", " ")
	tmp := o.Path + ".tmp"
	f, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o600)
	if err != nil {
		return err
	}
	if _, err := f.Write(b); err != nil {
		f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	return os.Rename(tmp, o.Path)
}

// Forget names no longer in the group (the owner took them out): nothing to maintain.
func (o *Owned) Forget(inGroup map[string]bool) int {
	n := 0
	for h := range o.Names {
		if !inGroup[h] {
			delete(o.Names, h)
			n++
		}
	}
	return n
}

// Due: up to max owned names to check now, the longest unchecked first.
func (o *Owned) Due(now time.Time, every time.Duration, max int) []string {
	var out []string
	for h, n := range o.Names {
		if now.Sub(n.Checked) >= every {
			out = append(out, h)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		a, b := o.Names[out[i]].Checked, o.Names[out[j]].Checked
		if !a.Equal(b) {
			return a.Before(b)
		}
		return out[i] < out[j]
	})
	if len(out) > max {
		out = out[:max]
	}
	return out
}
