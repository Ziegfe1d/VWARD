// Package journal is the write-ahead journal of routing operations, with the semantics of
// the shell journal (vward-routing-journal.sh): one directory per operation, records
// written atomically (temp + fsync + rename); «pending» is written BEFORE anything is sent
// and holds the pre-image and the expected post-image of every affected area. The state of
// an operation: resolved > unknown > done|failed > pending > plan. A pending or unknown
// operation blocks every new one (Gate). An operation id is used once: never replayed.
package journal

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

type Journal struct{ Dir string }

type Pending struct {
	Op       string            `json:"op"`
	Commands []string          `json:"commands"`
	Undo     []string          `json:"undo"`
	Pre      map[string]string `json:"pre"`  // area -> fingerprint before
	Post     map[string]string `json:"post"` // area -> expected fingerprint after
}

type Outcome struct {
	State   string   `json:"state"` // done | failed | unknown
	Reason  string   `json:"reason"`
	Applied int      `json:"applied"` // steps proven by the read after the batch
	Results []string `json:"results,omitempty"`
	Saved   bool     `json:"saved"` // «system configuration save» acknowledged
}

var opRe = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`)

var (
	ErrBlocked = errors.New("journal: a pending or unknown operation blocks new ones")
	ErrReused  = errors.New("journal: operation id already used")
)

func (j *Journal) dir(op string) string { return filepath.Join(j.Dir, op) }

func writeAtomic(path string, data []byte) error {
	tmp := path + ".tmp"
	f, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return err
	}
	if _, err := f.Write(data); err != nil {
		f.Close()
		os.Remove(tmp)
		return err
	}
	if err := f.Sync(); err != nil {
		f.Close()
		os.Remove(tmp)
		return err
	}
	if err := f.Close(); err != nil {
		os.Remove(tmp)
		return err
	}
	if err := os.Rename(tmp, path); err != nil {
		return err
	}
	d, err := os.Open(filepath.Dir(path))
	if err == nil {
		d.Sync()
		d.Close()
	}
	return nil
}

// State of one operation.
func (j *Journal) State(op string) string {
	d := j.dir(op)
	for _, s := range []string{"resolved", "unknown", "done", "failed", "pending", "plan"} {
		if _, err := os.Lstat(filepath.Join(d, s)); err == nil {
			if s == "unknown" || s == "done" || s == "failed" {
				return outcomeState(filepath.Join(d, s), s)
			}
			return s
		}
	}
	return "absent"
}

func outcomeState(path, def string) string {
	b, err := os.ReadFile(path)
	if err != nil {
		return "unknown"
	}
	var o Outcome
	if json.Unmarshal(b, &o) != nil || o.State != def {
		return "unknown" // a corrupt or contradictory record
	}
	return def
}

// Gate: no pending or unknown operation anywhere.
func (j *Journal) Gate() error {
	ents, err := os.ReadDir(j.Dir)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	for _, e := range ents {
		if !e.IsDir() || strings.HasPrefix(e.Name(), ".") {
			continue
		}
		switch j.State(e.Name()) {
		case "pending", "unknown", "plan":
			return fmt.Errorf("%w: %s", ErrBlocked, e.Name())
		}
	}
	return nil
}

// Begin: the operation directory and its pending record, before anything is sent.
func (j *Journal) Begin(p Pending) error {
	if !opRe.MatchString(p.Op) {
		return fmt.Errorf("journal: invalid operation id %q", p.Op)
	}
	if err := os.MkdirAll(j.Dir, 0o700); err != nil {
		return err
	}
	if err := j.Gate(); err != nil {
		return err
	}
	if err := os.Mkdir(j.dir(p.Op), 0o700); err != nil {
		if errors.Is(err, os.ErrExist) {
			return ErrReused
		}
		return err
	}
	b, _ := json.MarshalIndent(p, "", " ")
	return writeAtomic(filepath.Join(j.dir(p.Op), "pending"), b)
}

// Finish: the outcome record (done, failed or unknown).
func (j *Journal) Finish(op string, o Outcome) error {
	switch o.State {
	case "done", "failed", "unknown":
	default:
		return fmt.Errorf("journal: invalid outcome %q", o.State)
	}
	b, _ := json.MarshalIndent(o, "", " ")
	return writeAtomic(filepath.Join(j.dir(op), o.State), b)
}

// Pending record of an operation (recovery reads it after a crash).
func (j *Journal) Pending(op string) (*Pending, error) {
	b, err := os.ReadFile(filepath.Join(j.dir(op), "pending"))
	if err != nil {
		return nil, err
	}
	var p Pending
	if err := json.Unmarshal(b, &p); err != nil {
		return nil, err
	}
	return &p, nil
}

// Open: operations that are pending (a crash between send and outcome) or unknown, oldest name first.
func (j *Journal) Open() []string {
	ents, _ := os.ReadDir(j.Dir)
	var out []string
	for _, e := range ents {
		if e.IsDir() {
			if s := j.State(e.Name()); s == "pending" || s == "unknown" {
				out = append(out, e.Name())
			}
		}
	}
	sort.Strings(out)
	return out
}

// Resolve: later evidence closes an unknown or pending operation (done|failed), never a replay.
func (j *Journal) Resolve(op, state, reason string) error {
	if state != "done" && state != "failed" {
		return fmt.Errorf("journal: resolve to %q", state)
	}
	b, _ := json.Marshal(Outcome{State: state, Reason: reason})
	return writeAtomic(filepath.Join(j.dir(op), "resolved"), b)
}
