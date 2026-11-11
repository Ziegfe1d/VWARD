package main

import (
	"encoding/binary"
	"strings"
)

// queryName returns the asked name of a DNS query (A, AAAA or HTTPS) carried in an
// Ethernet frame to UDP port 53, or "". Answers, other types and malformed packets give "".
func queryName(frame []byte) string {
	if len(frame) < 14 {
		return ""
	}
	off := 12
	etype := binary.BigEndian.Uint16(frame[off:])
	off += 2
	for etype == 0x8100 || etype == 0x88a8 { // VLAN tags
		if len(frame) < off+4 {
			return ""
		}
		etype = binary.BigEndian.Uint16(frame[off+2:])
		off += 4
	}
	var udp []byte
	switch etype {
	case 0x0800:
		ip := frame[off:]
		if len(ip) < 20 || ip[0]>>4 != 4 || ip[9] != 17 {
			return ""
		}
		if binary.BigEndian.Uint16(ip[6:])&0x1fff != 0 || ip[6]&0x20 != 0 { // fragments
			return ""
		}
		ihl := int(ip[0]&0x0f) * 4
		if ihl < 20 || len(ip) < ihl+8 {
			return ""
		}
		udp = ip[ihl:]
	case 0x86dd:
		ip := frame[off:]
		if len(ip) < 48 || ip[0]>>4 != 6 || ip[6] != 17 {
			return ""
		}
		udp = ip[40:]
	default:
		return ""
	}
	if binary.BigEndian.Uint16(udp[2:]) != 53 {
		return ""
	}
	return dnsQuestion(udp[8:])
}

func dnsQuestion(m []byte) string {
	if len(m) < 12 {
		return ""
	}
	if m[2]&0x80 != 0 || m[2]&0x78 != 0 { // an answer, or not a standard query
		return ""
	}
	if binary.BigEndian.Uint16(m[4:]) < 1 {
		return ""
	}
	p := 12
	var b strings.Builder
	for {
		if p >= len(m) {
			return ""
		}
		l := int(m[p])
		p++
		if l == 0 {
			break
		}
		if l > 63 || p+l > len(m) || b.Len()+l+1 > 254 { // also rejects compression pointers
			return ""
		}
		if b.Len() > 0 {
			b.WriteByte('.')
		}
		b.Write(m[p : p+l])
		p += l
	}
	if p+4 > len(m) {
		return ""
	}
	switch binary.BigEndian.Uint16(m[p:]) {
	case 1, 28, 65:
	default:
		return ""
	}
	return normalizeName(b.String())
}
