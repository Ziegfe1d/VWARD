// Package router binds the executor to Keenetic's RCI: narrow reads of the areas a
// request touches (or one full read, the first start and recovery), and batches.
package router

import (
	"fmt"
	"time"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/ndm"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/rci"
)

type RCI struct {
	C      *rci.Client
	Narrow bool // false: every read is the whole running-config
	Timing map[string]time.Duration
}

func New(c *rci.Client, narrow bool) *RCI {
	return &RCI{C: c, Narrow: narrow, Timing: map[string]time.Duration{}}
}

func (r *RCI) timed(name string, f func() error) error {
	t0 := time.Now()
	err := f()
	r.Timing[name] += time.Since(t0)
	return err
}

// Full: the whole configuration, through RCI (no ndmc process).
func (r *RCI) Full() (*ndm.Model, string, error) {
	var text string
	err := r.timed("full", func() error {
		b, err := r.C.Get("show/running-config")
		if err != nil {
			return err
		}
		text, err = ndm.RunningFromRCI(b)
		return err
	})
	if err != nil {
		return nil, "", err
	}
	return ndm.ParseRunning(text), text, nil
}

// Read the areas ("groups", "routes", "doh").
func (r *RCI) Read(areas []string) (*ndm.Model, error) {
	if !r.Narrow {
		m, _, err := r.Full()
		return m, err
	}
	m := &ndm.Model{Groups: map[string]*ndm.Group{}, Read: map[string]bool{}}
	needDNS := false
	for _, a := range areas {
		switch a {
		case "groups":
			if err := r.timed("narrow:groups", func() error {
				b, err := r.C.Get("object-group/fqdn")
				if err != nil {
					return err
				}
				return ndm.GroupsFromRCI(b, m)
			}); err != nil {
				return nil, fmt.Errorf("groups: %w", err)
			}
		case "routes", "doh":
			needDNS = true
		default:
			return nil, fmt.Errorf("unknown area %q", a)
		}
	}
	if needDNS {
		if err := r.timed("narrow:dns-proxy", func() error {
			b, err := r.C.Get("dns-proxy")
			if err != nil {
				return err
			}
			return ndm.DNSProxyFromRCI(b, m)
		}); err != nil {
			return nil, fmt.Errorf("dns-proxy: %w", err)
		}
	}
	return m, nil
}

// Send one batch.
func (r *RCI) Send(cmds []string) ([]rci.Result, error) {
	var res []rci.Result
	err := r.timed("batch", func() error {
		var err error
		res, err = r.C.Parse(cmds)
		return err
	})
	return res, err
}
