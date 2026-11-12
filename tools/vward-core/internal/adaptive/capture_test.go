package adaptive

import (
	"net"
	"os"
	"testing"
	"time"
)

// The kernel filter hands over the query sent to port 53 on lo, and the name comes out.
func TestCaptureOnLoopback(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Skip("a packet socket needs root")
	}
	c, err := OpenCapture("lo")
	if err != nil {
		t.Skipf("no packet socket here: %v", err)
	}
	defer c.Close()
	conn, err := net.Dial("udp4", "127.0.0.1:53")
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	other, _ := net.Dial("udp4", "127.0.0.1:5353")
	defer other.Close()
	buf := make([]byte, 65536)
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		other.Write(dnsQuery("mdns.example.com", 1, false))
		conn.Write(dnsQuery("captured.example.com", 1, false))
		name, err := c.Next(buf)
		if err != nil {
			t.Fatal(err)
		}
		if name == "mdns.example.com" {
			t.Fatal("port 5353 passed the filter")
		}
		if name == "captured.example.com" {
			return
		}
	}
	t.Fatal("the query was not captured")
}
