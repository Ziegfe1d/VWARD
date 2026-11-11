// Package recovery closes the operations a crash or a lost answer left open (pending or
// unknown) by evidence only: the areas the pending record names are read again and compared
// with its fingerprints. The expected post-image: the batch was applied (done). The
// pre-image: nothing was applied (failed). Anything else stays open and keeps blocking new
// operations until the owner looks: nothing is ever sent again (no replay) and nothing is
// compensated here. Only the local journal is written; the router is only read.
package recovery

import (
	"sort"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/exec"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/journal"
	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/ndm"
)

// Reader: narrow reads of router areas.
type Reader interface {
	Read(areas []string) (*ndm.Model, error)
}

// Report of one open operation.
type Report struct {
	Op  string
	Was string // pending | unknown
	Now string // done | failed | open
	Why string
}

// Run looks at every open operation, oldest first. write=false only reports.
func Run(r Reader, j *journal.Journal, write bool) ([]Report, error) {
	var out []Report
	for _, op := range j.Open() {
		rep := Report{Op: op, Was: j.State(op), Now: "open"}
		p, err := j.Pending(op)
		if err != nil || len(p.Pre) == 0 || len(p.Post) == 0 {
			rep.Why = "no readable pending record: the owner decides"
			out = append(out, rep)
			continue
		}
		areas := make([]string, 0, len(p.Pre))
		for a := range p.Pre {
			areas = append(areas, a)
		}
		sort.Strings(areas)
		m, err := r.Read(exec.ReadAreas(areas))
		if err != nil {
			rep.Why = "router not read: " + err.Error()
			out = append(out, rep)
			continue
		}
		now := map[string]string{}
		for _, a := range areas {
			now[a] = m.Fingerprint(a)
		}
		switch {
		case same(now, p.Post):
			rep.Now, rep.Why = "done", "the read after restart shows the batch applied"
		case same(now, p.Pre):
			rep.Now, rep.Why = "failed", "the read after restart shows nothing applied"
		default:
			rep.Why = "the router holds neither the image before nor the one expected after: the owner decides"
		}
		if write && rep.Now != "open" {
			if err := j.Resolve(op, rep.Now, "recovery: "+rep.Why); err != nil {
				return out, err
			}
		}
		out = append(out, rep)
	}
	return out, nil
}

func same(a, b map[string]string) bool {
	if len(a) != len(b) {
		return false
	}
	for k, v := range a {
		if bv, ok := b[k]; !ok || bv != v {
			return false
		}
	}
	return true
}
