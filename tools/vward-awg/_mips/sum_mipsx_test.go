// VWARD: update32 must give the generic code's state for any input, including
// an accumulator left unreduced (up to 2 * (2^130 - 5)) by a previous run.

//go:build gc && !purego && (mips || mipsle)

package poly1305

import (
	"math/rand"
	"testing"
)

func TestUpdate32MatchesGeneric(t *testing.T) {
	rng := rand.New(rand.NewSource(1))
	for i := 0; i < 20000; i++ {
		var key [32]byte
		rng.Read(key[:])
		var a, b macState
		initialize(&key, &a)
		b = a
		if i%3 == 0 { // an unreduced accumulator
			a.h = [3]uint64{rng.Uint64(), rng.Uint64(), uint64(rng.Intn(8))}
			if a.h[2] == 7 {
				a.h[2] = 6
			}
			b.h = a.h
		}
		for j := 0; j < 3; j++ {
			msg := make([]byte, rng.Intn(200))
			rng.Read(msg)
			if i%5 == 0 {
				for k := range msg {
					msg[k] = 0xff
				}
			}
			update32(&a, msg)
			updateGeneric(&b, msg)
			var ta, tb [16]byte
			finalize(&ta, &a.h, &a.s)
			finalize(&tb, &b.h, &b.s)
			if ta != tb {
				t.Fatalf("case %d/%d: tag %x != %x", i, j, ta, tb)
			}
		}
	}
}
