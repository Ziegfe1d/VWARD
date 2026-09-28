// Copyright 2018 The Go Authors. All rights reserved.
// Use of this source code is governed by a BSD-style
// license that can be found in the LICENSE file.

// VWARD: Poly1305 for 32-bit MIPS routers.  The generic code keeps the
// accumulator in 64-bit limbs and multiplies with bits.Mul64, which a 32-bit
// CPU runs as a function of four multiplications.  Here each run of blocks
// works on five 26-bit limbs (the "donna-32" layout), where every product is
// one 32x32->64 multiplication; the state is converted back to the 64-bit
// limbs between runs, so New, Sum and finalize stay the package's own.
// Added to golang.org/x/crypto/internal/poly1305 at build time.

//go:build gc && !purego && (mips || mipsle)

package poly1305

import "encoding/binary"

type mac struct{ macMips }

type macMips struct {
	macState

	buffer [TagSize]byte
	offset int
}

func (h *macMips) Write(p []byte) (int, error) {
	nn := len(p)
	if h.offset > 0 {
		n := copy(h.buffer[h.offset:], p)
		if h.offset+n < TagSize {
			h.offset += n
			return nn, nil
		}
		p = p[n:]
		h.offset = 0
		update32(&h.macState, h.buffer[:])
	}
	if n := len(p) - (len(p) % TagSize); n > 0 {
		update32(&h.macState, p[:n])
		p = p[n:]
	}
	if len(p) > 0 {
		h.offset += copy(h.buffer[h.offset:], p)
	}
	return nn, nil
}

func (h *macMips) Sum(out *[TagSize]byte) {
	state := h.macState
	if h.offset > 0 {
		update32(&state, h.buffer[:h.offset])
	}
	finalize(out, &state.h, &state.s)
}

const mask26 = 0x3ffffff

// update32 is updateGeneric on 26-bit limbs: the same blocks, the same padding
// of a short last block (a 1 byte, no 2^128 bit), the same partial reduction.
func update32(state *macState, msg []byte) {
	// r is clamped, so its limbs need no further masking than 26 bits.
	rl, rh := state.r[0], state.r[1]
	r0 := uint32(rl) & mask26
	r1 := uint32(rl>>26) & mask26
	r2 := uint32(rl>>52|rh<<12) & mask26
	r3 := uint32(rh>>14) & mask26
	r4 := uint32(rh>>40) & mask26
	s1, s2, s3, s4 := r1*5, r2*5, r3*5, r4*5

	hl, hm, hh := state.h[0], state.h[1], state.h[2]
	h0 := uint32(hl) & mask26
	h1 := uint32(hl>>26) & mask26
	h2 := uint32(hl>>52|hm<<12) & mask26
	h3 := uint32(hm>>14) & mask26
	h4 := uint32(hm>>40) | uint32(hh<<24)

	for len(msg) > 0 {
		var hibit uint32
		var block []byte
		var buf [TagSize]byte
		if len(msg) >= TagSize {
			block = msg[:TagSize]
			msg = msg[TagSize:]
			hibit = 1 << 24
		} else {
			copy(buf[:], msg)
			buf[len(msg)] = 1
			block = buf[:]
			msg = nil
		}
		t0 := binary.LittleEndian.Uint32(block[0:4])
		t1 := binary.LittleEndian.Uint32(block[4:8])
		t2 := binary.LittleEndian.Uint32(block[8:12])
		t3 := binary.LittleEndian.Uint32(block[12:16])
		h0 += t0 & mask26
		h1 += (t0>>26 | t1<<6) & mask26
		h2 += (t1>>20 | t2<<12) & mask26
		h3 += (t2>>14 | t3<<18) & mask26
		h4 += t3>>8 | hibit

		d0 := uint64(h0)*uint64(r0) + uint64(h1)*uint64(s4) + uint64(h2)*uint64(s3) + uint64(h3)*uint64(s2) + uint64(h4)*uint64(s1)
		d1 := uint64(h0)*uint64(r1) + uint64(h1)*uint64(r0) + uint64(h2)*uint64(s4) + uint64(h3)*uint64(s3) + uint64(h4)*uint64(s2)
		d2 := uint64(h0)*uint64(r2) + uint64(h1)*uint64(r1) + uint64(h2)*uint64(r0) + uint64(h3)*uint64(s4) + uint64(h4)*uint64(s3)
		d3 := uint64(h0)*uint64(r3) + uint64(h1)*uint64(r2) + uint64(h2)*uint64(r1) + uint64(h3)*uint64(r0) + uint64(h4)*uint64(s4)
		d4 := uint64(h0)*uint64(r4) + uint64(h1)*uint64(r3) + uint64(h2)*uint64(r2) + uint64(h3)*uint64(r1) + uint64(h4)*uint64(r0)

		c := d0 >> 26
		h0 = uint32(d0) & mask26
		d1 += c
		c = d1 >> 26
		h1 = uint32(d1) & mask26
		d2 += c
		c = d2 >> 26
		h2 = uint32(d2) & mask26
		d3 += c
		c = d3 >> 26
		h3 = uint32(d3) & mask26
		d4 += c
		c = d4 >> 26
		h4 = uint32(d4) & mask26
		h0 += uint32(c) * 5
		h1 += h0 >> 26
		h0 &= mask26
	}

	// Carry through so the limbs do not overlap, then back to 64-bit limbs.
	// The value stays below 2^130 + 2^26, well under 2 * (2^130 - 5).
	h2 += h1 >> 26
	h1 &= mask26
	h3 += h2 >> 26
	h2 &= mask26
	h4 += h3 >> 26
	h3 &= mask26
	state.h[0] = uint64(h0) | uint64(h1)<<26 | uint64(h2)<<52
	state.h[1] = uint64(h2)>>12 | uint64(h3)<<14 | uint64(h4)<<40
	state.h[2] = uint64(h4) >> 24
}
