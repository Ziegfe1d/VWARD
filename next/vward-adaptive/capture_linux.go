package main

import (
	"fmt"
	"net"
	"syscall"
)

func htons(v uint16) uint16 { return v<<8 | v>>8 }

// «udp dst port 53» for IPv4 (no fragments) and IPv6 (tcpdump -dd): the kernel hands over
// only DNS queries, not the LAN's traffic.
var dnsFilter = []syscall.SockFilter{
	{Code: 0x28, Jt: 0, Jf: 0, K: 0x0000000c},
	{Code: 0x15, Jt: 0, Jf: 4, K: 0x000086dd},
	{Code: 0x30, Jt: 0, Jf: 0, K: 0x00000014},
	{Code: 0x15, Jt: 0, Jf: 11, K: 0x00000011},
	{Code: 0x28, Jt: 0, Jf: 0, K: 0x00000038},
	{Code: 0x15, Jt: 8, Jf: 9, K: 0x00000035},
	{Code: 0x15, Jt: 0, Jf: 8, K: 0x00000800},
	{Code: 0x30, Jt: 0, Jf: 0, K: 0x00000017},
	{Code: 0x15, Jt: 0, Jf: 6, K: 0x00000011},
	{Code: 0x28, Jt: 0, Jf: 0, K: 0x00000014},
	{Code: 0x45, Jt: 4, Jf: 0, K: 0x00001fff},
	{Code: 0xb1, Jt: 0, Jf: 0, K: 0x0000000e},
	{Code: 0x48, Jt: 0, Jf: 0, K: 0x00000010},
	{Code: 0x15, Jt: 0, Jf: 1, K: 0x00000035},
	{Code: 0x06, Jt: 0, Jf: 0, K: 0x00040000},
	{Code: 0x06, Jt: 0, Jf: 0, K: 0x00000000},
}

type capture struct{ fd int }

// openCapture: a packet socket on dev that receives DNS queries only.
func openCapture(dev string) (*capture, error) {
	ifi, err := net.InterfaceByName(dev)
	if err != nil {
		return nil, err
	}
	fd, err := syscall.Socket(syscall.AF_PACKET, syscall.SOCK_RAW, int(htons(syscall.ETH_P_ALL)))
	if err != nil {
		return nil, fmt.Errorf("packet socket: %v", err)
	}
	if err := syscall.AttachLsf(fd, dnsFilter); err != nil {
		syscall.Close(fd)
		return nil, fmt.Errorf("filter: %v", err)
	}
	if err := syscall.Bind(fd, &syscall.SockaddrLinklayer{Protocol: htons(syscall.ETH_P_ALL), Ifindex: ifi.Index}); err != nil {
		syscall.Close(fd)
		return nil, fmt.Errorf("bind %s: %v", dev, err)
	}
	// A second's timeout: the reader notices a stop.
	tv := syscall.Timeval{Sec: 1}
	_ = syscall.SetsockoptTimeval(fd, syscall.SOL_SOCKET, syscall.SO_RCVTIMEO, &tv)
	return &capture{fd: fd}, nil
}

// next: the next asked name; "" on a timeout or a packet that is not a query.
func (c *capture) next(buf []byte) (string, error) {
	n, _, err := syscall.Recvfrom(c.fd, buf, 0)
	if err != nil {
		if err == syscall.EAGAIN || err == syscall.EINTR {
			return "", nil
		}
		return "", err
	}
	return queryName(buf[:n]), nil
}

func (c *capture) close() { syscall.Close(c.fd) }

// bindControl ties a dialer's socket to one device (the direct or the VPN path).
func bindControl(dev string) func(network, address string, rc syscall.RawConn) error {
	return func(network, address string, rc syscall.RawConn) error {
		var serr error
		err := rc.Control(func(fd uintptr) {
			serr = syscall.SetsockoptString(int(fd), syscall.SOL_SOCKET, syscall.SO_BINDTODEVICE, dev)
		})
		if err != nil {
			return err
		}
		return serr
	}
}
