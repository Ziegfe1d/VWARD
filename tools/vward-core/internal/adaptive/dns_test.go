package adaptive

import (
	"encoding/binary"
	"testing"
)

func dnsQuery(name string, qtype uint16, answer bool) []byte {
	m := make([]byte, 12)
	binary.BigEndian.PutUint16(m[0:], 0x1234)
	if answer {
		m[2] = 0x81
	} else {
		m[2] = 0x01
	}
	binary.BigEndian.PutUint16(m[4:], 1)
	for _, l := range splitDots(name) {
		m = append(m, byte(len(l)))
		m = append(m, l...)
	}
	m = append(m, 0, byte(qtype>>8), byte(qtype), 0, 1)
	return m
}

func splitDots(s string) []string {
	var out []string
	cur := ""
	for i := 0; i < len(s); i++ {
		if s[i] == '.' {
			out = append(out, cur)
			cur = ""
			continue
		}
		cur += string(s[i])
	}
	return append(out, cur)
}

func udp(payload []byte, dport uint16) []byte {
	u := make([]byte, 8)
	binary.BigEndian.PutUint16(u[0:], 40000)
	binary.BigEndian.PutUint16(u[2:], dport)
	binary.BigEndian.PutUint16(u[4:], uint16(8+len(payload)))
	return append(u, payload...)
}

func ipv4Frame(u []byte, vlan bool) []byte {
	eth := make([]byte, 12)
	if vlan {
		eth = append(eth, 0x81, 0x00, 0, 5)
	}
	eth = append(eth, 0x08, 0x00)
	ip := make([]byte, 20)
	ip[0] = 0x45
	ip[9] = 17
	return append(append(eth, ip...), u...)
}

func ipv6Frame(u []byte) []byte {
	eth := append(make([]byte, 12), 0x86, 0xdd)
	ip := make([]byte, 40)
	ip[0] = 0x60
	ip[6] = 17
	return append(append(eth, ip...), u...)
}

func TestQueryName(t *testing.T) {
	q := dnsQuery("WWW.Example.COM", 1, false)
	for _, c := range []struct {
		name  string
		frame []byte
		want  string
	}{
		{"ipv4 A", ipv4Frame(udp(q, 53), false), "www.example.com"},
		{"vlan", ipv4Frame(udp(q, 53), true), "www.example.com"},
		{"ipv6 AAAA", ipv6Frame(udp(dnsQuery("v6.example.com", 28, false), 53)), "v6.example.com"},
		{"HTTPS type", ipv4Frame(udp(dnsQuery("h.example.com", 65, false), 53), false), "h.example.com"},
		{"answer", ipv4Frame(udp(dnsQuery("a.example.com", 1, true), 53), false), ""},
		{"TXT", ipv4Frame(udp(dnsQuery("t.example.com", 16, false), 53), false), ""},
		{"other port", ipv4Frame(udp(q, 5353), false), ""},
		{"local", ipv4Frame(udp(dnsQuery("nas.lan", 1, false), 53), false), ""},
		{"truncated", ipv4Frame(udp(q, 53), false)[:50], ""},
		{"empty", nil, ""},
	} {
		if got := queryName(c.frame); got != c.want {
			t.Errorf("%s: %q, want %q", c.name, got, c.want)
		}
	}
	// A compression pointer in the question is refused, not followed.
	bad := dnsQuery("x.example.com", 1, false)
	bad[12] = 0xc0
	if got := queryName(ipv4Frame(udp(bad, 53), false)); got != "" {
		t.Errorf("pointer: %q", got)
	}
}
