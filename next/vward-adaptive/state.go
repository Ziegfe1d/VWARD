package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"time"
)

// Own is a name this program put into the group. Only these are ever taken out again.
type Own struct {
	Added    time.Time `json:"added"`
	LastSeen time.Time `json:"last_seen"`
	Why      string    `json:"why,omitempty"`
}

type State struct {
	Own map[string]*Own `json:"own"`
	// Names the owner took out of the group: not put back for 30 days.
	Refused map[string]time.Time `json:"refused,omitempty"`
}

func newState() *State { return &State{Own: map[string]*Own{}, Refused: map[string]time.Time{}} }

func loadState(path string) (*State, error) {
	s := newState()
	b, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return s, nil
	}
	if err != nil {
		return s, err
	}
	if err := json.Unmarshal(b, s); err != nil {
		return newState(), err
	}
	if s.Own == nil {
		s.Own = map[string]*Own{}
	}
	if s.Refused == nil {
		s.Refused = map[string]time.Time{}
	}
	return s, nil
}

// save writes atomically: a cut power never leaves half a file.
func (s *State) save(path string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	b, err := json.MarshalIndent(s, "", " ")
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	f, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o644)
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
	return os.Rename(tmp, path)
}

func (s *State) ownNames() []string {
	n := make([]string, 0, len(s.Own))
	for k := range s.Own {
		n = append(n, k)
	}
	sort.Strings(n)
	return n
}
