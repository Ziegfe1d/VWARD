// VWARD: everywhere but 32-bit MIPS the standard pool stays (see vw_mipsx.go).

//go:build !mips && !mipsle

package conn

import "sync"

type vwPool = sync.Pool
