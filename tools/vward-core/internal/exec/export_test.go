package exec

import "testing"

// For tests of other packages that run through the executor (package exec_test): the fake
// Keenetic with HTTP RCI, its rendered configuration and the batches it got.
type FakeKeenetic struct{ f *fakeKeenetic }

func NewFakeKeenetic(t *testing.T, cfg string) *FakeKeenetic { return &FakeKeenetic{newFake(t, cfg)} }
func (k *FakeKeenetic) Addr() string                         { return k.f.addr() }
func (k *FakeKeenetic) Running() string                      { k.f.mu.Lock(); defer k.f.mu.Unlock(); return k.f.running() }
func (k *FakeKeenetic) Batches() [][]string {
	k.f.mu.Lock()
	defer k.f.mu.Unlock()
	return append([][]string(nil), k.f.batches...)
}
func (k *FakeKeenetic) RefuseOn(s string) { k.f.mu.Lock(); k.f.refuseOn = s; k.f.mu.Unlock() }

const OwnerCfg = ownerCfg
