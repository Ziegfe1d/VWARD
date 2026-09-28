package main

import (
	"errors"
	"strings"
	"testing"
)

const (
	priv = "OOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOA="
	pub  = "PPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPA="
	hpk  = "HHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHA="
)

func noLookup(string) ([]string, error) { return nil, errors.New("no DNS in tests") }

func TestAmneziaWG3File(t *testing.T) {
	conf := "[Interface]\r\nAddress = 10.66.0.25/32\r\nDNS = 10.66.0.1\r\nPrivateKey = " + priv + "\r\n" +
		"Jc = 7\nJmin = 10\nJmax = 80\nS1 = 600\nS2 = 150\nS3 = 800\nS4 = 12\nH1 = 1\nH2 = 2\nH3 = 3\nH4 = 100000000-1500000000\n" +
		"HeaderProtectionKey = " + hpk + "\nRekeyAfterTime = 100-120\nRekeyTimeout = 3-8\nRejectAfterTime = 150-180\n" +
		"KeepaliveTimeout = 7-13\nMaxHandshakeAttempts = 15-20\nContentPaddingAddition = 10-100\nRandomTrailers = true\n" +
		"DisableCookies = 0\nI1 = <b 0x52><rd 9>\nI2 =\nMTU = 1380\n\n[Peer]\nPublicKey = " + pub + "\n" +
		"AllowedIPs = 0.0.0.0/0, ::/0\nEndpoint = 203.0.113.10:3954\nPersistentKeepalive = 25-35\n"
	c, err := ParseConf(strings.NewReader(conf), noLookup)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"private_key=38e38e", "header_protection_key=1c71c7", "h4=100000000-1500000000\n",
		"rekey_after_time=100-120\n", "content_padding_addition=10-100\n", "random_trailers=true\n",
		"disable_cookies=false\n", "i1=<b 0x52><rd 9>\n", "replace_peers=true\npublic_key=3cf3cf",
		"allowed_ip=0.0.0.0/0\nallowed_ip=::/0\n", "endpoint=203.0.113.10:3954\n", "persistent_keepalive_interval=25-35\n"} {
		if !strings.Contains(c.UAPI, want) {
			t.Errorf("missing %q in\n%s", want, c.UAPI)
		}
	}
	if strings.Contains(c.UAPI, "i2=") || strings.Contains(c.UAPI, "dns") {
		t.Errorf("empty I2 or DNS went to the tunnel:\n%s", c.UAPI)
	}
	// The device settings come before the peer, or the protocol takes them as the peer's.
	if strings.Index(c.UAPI, "jc=") > strings.Index(c.UAPI, "public_key=") {
		t.Errorf("device settings after the peer")
	}
	if c.MTU != 1380 || len(c.Addresses) != 1 || c.Addresses[0].String() != "10.66.0.25/32" {
		t.Errorf("MTU %d, addresses %v", c.MTU, c.Addresses)
	}
}

func TestServerName(t *testing.T) {
	conf := "[Interface]\nPrivateKey = " + priv + "\n[Peer]\nPublicKey = " + pub + "\nEndpoint = de.example:2905\n"
	c, err := ParseConf(strings.NewReader(conf), func(h string) ([]string, error) {
		return []string{"2001:db8::1", "198.51.100.24"}, nil
	})
	if err != nil || !strings.Contains(c.UAPI, "endpoint=198.51.100.24:2905\n") {
		t.Fatalf("%v %v", err, c)
	}
	if _, err := ParseConf(strings.NewReader(conf), noLookup); err == nil {
		t.Fatal("a name that does not resolve must fail")
	}
}

// Errors name the setting and the line, never the value.
func TestErrorsKeepKeysOut(t *testing.T) {
	secret := "c2VjcmV0c2VjcmV0c2VjcmV0c2VjcmV0c2VjcmV0MTI="
	for _, conf := range []string{
		"[Interface]\nPrivateKey = " + secret + "x\n",
		"[Interface]\nPrivateKey = " + priv + "\nHeaderProtectionKey = " + secret[:20] + "\n",
		"[Interface]\nPrivateKey = " + priv + "\n[Peer]\nPresharedKey = " + secret + "\n",
		"[Interface]\nPrivateKey = " + priv + "\nS1 = " + secret + "\n",
		"[Interface]\nPrivateKey = " + priv + "\nUnknownThing = " + secret + "\n",
		"[Interface]\nPrivateKey = " + priv + "\n",
		"[Interface]\nPrivateKey = " + priv + "\n[Peer]\nAllowedIPs = " + secret + "\n",
		"[Wrong]\n",
	} {
		_, err := ParseConf(strings.NewReader(conf), noLookup)
		if err == nil {
			t.Errorf("accepted:\n%s", conf)
			continue
		}
		if strings.Contains(err.Error(), secret[:12]) {
			t.Errorf("error shows the value: %v", err)
		}
	}
}
