// VWARD: 32-bit MIPS routers.  Go runs every 64-bit atomic operation on these
// CPUs under one spinlock shared by the whole program, and amneziawg-go does
// several per packet (the send nonce, traffic counters, the obfuscation
// ranges, sync.Pool's own counters): with four threads they queued on that one
// lock and a profile on a Viva (MT7621) put 23% of the program's CPU there.
// Here each value has its own small mutex, and the pools are plain free lists.
// Added to amneziawg-go at build time by _mips/prepare.sh.

//go:build mips || mipsle

package device

import "sync"

type u64 struct {
	mu sync.Mutex
	v  uint64
}

func (a *u64) Load() uint64         { a.mu.Lock(); v := a.v; a.mu.Unlock(); return v }
func (a *u64) Store(v uint64)       { a.mu.Lock(); a.v = v; a.mu.Unlock() }
func (a *u64) Add(d uint64) uint64  { a.mu.Lock(); a.v += d; v := a.v; a.mu.Unlock(); return v }
func (a *u64) Swap(v uint64) uint64 { a.mu.Lock(); o := a.v; a.v = v; a.mu.Unlock(); return o }
func (a *u64) CompareAndSwap(o, n uint64) bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.v != o {
		return false
	}
	a.v = n
	return true
}

type i64 struct {
	mu sync.Mutex
	v  int64
}

func (a *i64) Load() int64        { a.mu.Lock(); v := a.v; a.mu.Unlock(); return v }
func (a *i64) Store(v int64)      { a.mu.Lock(); a.v = v; a.mu.Unlock() }
func (a *i64) Add(d int64) int64  { a.mu.Lock(); a.v += d; v := a.v; a.mu.Unlock(); return v }
func (a *i64) Swap(v int64) int64 { a.mu.Lock(); o := a.v; a.v = v; a.mu.Unlock(); return o }
func (a *i64) CompareAndSwap(o, n int64) bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.v != o {
		return false
	}
	a.v = n
	return true
}

// vwPoolMax bounds what a free list keeps (message buffers are 64 KiB each).
const vwPoolMax = 128

type vwPool struct {
	New   func() any
	mu    sync.Mutex
	items []any
}

func (p *vwPool) Get() any {
	p.mu.Lock()
	if n := len(p.items); n > 0 {
		x := p.items[n-1]
		p.items[n-1] = nil
		p.items = p.items[:n-1]
		p.mu.Unlock()
		return x
	}
	p.mu.Unlock()
	if p.New != nil {
		return p.New()
	}
	return nil
}

func (p *vwPool) Put(x any) {
	p.mu.Lock()
	if len(p.items) < vwPoolMax {
		p.items = append(p.items, x)
	}
	p.mu.Unlock()
}
