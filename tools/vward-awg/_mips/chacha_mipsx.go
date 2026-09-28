// Copyright 2018 The Go Authors. All rights reserved.
// Use of this source code is governed by a BSD-style
// license that can be found in the LICENSE file.

// VWARD: ChaCha20 for 32-bit MIPS routers.  The same algorithm as
// xorKeyStreamBlocksGeneric, with the quarter rounds written out: on mips the
// compiler has no rotate instruction to intrinsify, so quarterRound is too
// costly to inline and each 64-byte block made 80 function calls.
// Written out from xorKeyStreamBlocksGeneric of x/crypto v0.42.0; added to
// golang.org/x/crypto at build time by prepare.sh.

//go:build gc && !purego && (mips || mipsle)

package chacha20

import "encoding/binary"

const bufSize = blockSize

func (s *Cipher) xorKeyStreamBlocks(dst, src []byte) {
	if len(dst) != len(src) || len(dst)%blockSize != 0 {
		panic("chacha20: internal error: wrong dst and/or src length")
	}
	var (
		c0, c1, c2, c3   = j0, j1, j2, j3
		c4, c5, c6, c7   = s.key[0], s.key[1], s.key[2], s.key[3]
		c8, c9, c10, c11 = s.key[4], s.key[5], s.key[6], s.key[7]
		c13, c14, c15    = s.nonce[0], s.nonce[1], s.nonce[2]
	)
	for len(src) >= 64 && len(dst) >= 64 {
		x0, x1, x2, x3 := c0, c1, c2, c3
		x4, x5, x6, x7 := c4, c5, c6, c7
		x8, x9, x10, x11 := c8, c9, c10, c11
		x12, x13, x14, x15 := s.counter, c13, c14, c15
		for i := 0; i < 10; i++ {
			x0 += x4
			x12 ^= x0
			x12 = x12<<16 | x12>>16
			x8 += x12
			x4 ^= x8
			x4 = x4<<12 | x4>>20
			x0 += x4
			x12 ^= x0
			x12 = x12<<8 | x12>>24
			x8 += x12
			x4 ^= x8
			x4 = x4<<7 | x4>>25
			x1 += x5
			x13 ^= x1
			x13 = x13<<16 | x13>>16
			x9 += x13
			x5 ^= x9
			x5 = x5<<12 | x5>>20
			x1 += x5
			x13 ^= x1
			x13 = x13<<8 | x13>>24
			x9 += x13
			x5 ^= x9
			x5 = x5<<7 | x5>>25
			x2 += x6
			x14 ^= x2
			x14 = x14<<16 | x14>>16
			x10 += x14
			x6 ^= x10
			x6 = x6<<12 | x6>>20
			x2 += x6
			x14 ^= x2
			x14 = x14<<8 | x14>>24
			x10 += x14
			x6 ^= x10
			x6 = x6<<7 | x6>>25
			x3 += x7
			x15 ^= x3
			x15 = x15<<16 | x15>>16
			x11 += x15
			x7 ^= x11
			x7 = x7<<12 | x7>>20
			x3 += x7
			x15 ^= x3
			x15 = x15<<8 | x15>>24
			x11 += x15
			x7 ^= x11
			x7 = x7<<7 | x7>>25
			x0 += x5
			x15 ^= x0
			x15 = x15<<16 | x15>>16
			x10 += x15
			x5 ^= x10
			x5 = x5<<12 | x5>>20
			x0 += x5
			x15 ^= x0
			x15 = x15<<8 | x15>>24
			x10 += x15
			x5 ^= x10
			x5 = x5<<7 | x5>>25
			x1 += x6
			x12 ^= x1
			x12 = x12<<16 | x12>>16
			x11 += x12
			x6 ^= x11
			x6 = x6<<12 | x6>>20
			x1 += x6
			x12 ^= x1
			x12 = x12<<8 | x12>>24
			x11 += x12
			x6 ^= x11
			x6 = x6<<7 | x6>>25
			x2 += x7
			x13 ^= x2
			x13 = x13<<16 | x13>>16
			x8 += x13
			x7 ^= x8
			x7 = x7<<12 | x7>>20
			x2 += x7
			x13 ^= x2
			x13 = x13<<8 | x13>>24
			x8 += x13
			x7 ^= x8
			x7 = x7<<7 | x7>>25
			x3 += x4
			x14 ^= x3
			x14 = x14<<16 | x14>>16
			x9 += x14
			x4 ^= x9
			x4 = x4<<12 | x4>>20
			x3 += x4
			x14 ^= x3
			x14 = x14<<8 | x14>>24
			x9 += x14
			x4 ^= x9
			x4 = x4<<7 | x4>>25
		}
		le := binary.LittleEndian
		le.PutUint32(dst[0:4], le.Uint32(src[0:4])^(x0+c0))
		le.PutUint32(dst[4:8], le.Uint32(src[4:8])^(x1+c1))
		le.PutUint32(dst[8:12], le.Uint32(src[8:12])^(x2+c2))
		le.PutUint32(dst[12:16], le.Uint32(src[12:16])^(x3+c3))
		le.PutUint32(dst[16:20], le.Uint32(src[16:20])^(x4+c4))
		le.PutUint32(dst[20:24], le.Uint32(src[20:24])^(x5+c5))
		le.PutUint32(dst[24:28], le.Uint32(src[24:28])^(x6+c6))
		le.PutUint32(dst[28:32], le.Uint32(src[28:32])^(x7+c7))
		le.PutUint32(dst[32:36], le.Uint32(src[32:36])^(x8+c8))
		le.PutUint32(dst[36:40], le.Uint32(src[36:40])^(x9+c9))
		le.PutUint32(dst[40:44], le.Uint32(src[40:44])^(x10+c10))
		le.PutUint32(dst[44:48], le.Uint32(src[44:48])^(x11+c11))
		le.PutUint32(dst[48:52], le.Uint32(src[48:52])^(x12+s.counter))
		le.PutUint32(dst[52:56], le.Uint32(src[52:56])^(x13+c13))
		le.PutUint32(dst[56:60], le.Uint32(src[56:60])^(x14+c14))
		le.PutUint32(dst[60:64], le.Uint32(src[60:64])^(x15+c15))
		s.counter += 1
		src, dst = src[blockSize:], dst[blockSize:]
	}
}
