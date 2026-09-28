// VWARD: everywhere but 32-bit MIPS the standard types stay (see vw_mipsx.go).

//go:build !mips && !mipsle

package device

import (
	"sync"
	"sync/atomic"
)

type u64 = atomic.Uint64
type i64 = atomic.Int64
type vwPool = sync.Pool
