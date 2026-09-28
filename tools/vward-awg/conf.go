package main

// An AmneziaWG .conf (wg-quick style, AmneziaWG 3.x settings included) turned
// into amneziawg-go's configuration protocol.  Key values never go into an
// error message: only the setting's name and the line number do.

import (
	"bufio"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"io"
	"net"
	"net/netip"
	"strconv"
	"strings"
)

// Conf is what the tunnel needs besides the protocol text.
type Conf struct {
	UAPI      string
	MTU       int
	Addresses []netip.Prefix
	Endpoints []string
}

// Interface settings the engine passes on as they are (numbers or ranges "a-b").
var ifaceRange = map[string]string{
	"jc": "jc", "jmin": "jmin", "jmax": "jmax",
	"s1": "s1", "s2": "s2", "s3": "s3", "s4": "s4",
	"h1": "h1", "h2": "h2", "h3": "h3", "h4": "h4",
	"contentpaddingaddition": "content_padding_addition",
	"rekeyaftertime":         "rekey_after_time",
	"rekeytimeout":           "rekey_timeout",
	"rejectaftertime":        "reject_after_time",
	"keepalivetimeout":       "keepalive_timeout",
	"maxhandshakeattempts":   "max_handshake_attempts",
	"listenport":             "listen_port",
	"fwmark":                 "fwmark",
}

// Special junk packets: their own small language, passed as written.
var ifaceText = map[string]string{"i1": "i1", "i2": "i2", "i3": "i3", "i4": "i4", "i5": "i5"}

var ifaceBool = map[string]string{"randomtrailers": "random_trailers", "disablecookies": "disable_cookies"}

// wg-quick settings for the host, not for the protocol: the router does these.
var ifaceHost = map[string]bool{"dns": true, "table": true, "preup": true, "postup": true,
	"predown": true, "postdown": true, "saveconfig": true}

type confError struct {
	line int
	what string
}

func (e *confError) Error() string {
	if e.line > 0 {
		return fmt.Sprintf("line %d: %s", e.line, e.what)
	}
	return e.what
}

func keyHex(v string) (string, bool) {
	b, err := base64.StdEncoding.DecodeString(v)
	if err != nil || len(b) != 32 {
		return "", false
	}
	return hex.EncodeToString(b), true
}

func validRange(v string) bool {
	lo, hi, found := strings.Cut(v, "-")
	a, err := strconv.ParseUint(strings.TrimSpace(lo), 10, 32)
	if err != nil {
		return false
	}
	if !found {
		return true
	}
	b, err := strconv.ParseUint(strings.TrimSpace(hi), 10, 32)
	return err == nil && b >= a
}

func cleanRange(v string) string { return strings.ReplaceAll(v, " ", "") }

// resolve turns "host:port" into "ip:port"; the protocol takes addresses only.
func resolve(ep string, lookup func(string) ([]string, error)) (string, error) {
	host, port, err := net.SplitHostPort(ep)
	if err != nil {
		return "", err
	}
	if _, err := strconv.ParseUint(port, 10, 16); err != nil {
		return "", err
	}
	if a, err := netip.ParseAddr(host); err == nil {
		return net.JoinHostPort(a.String(), port), nil
	}
	addrs, err := lookup(host)
	if err != nil || len(addrs) == 0 {
		return "", fmt.Errorf("server name %s does not resolve", host)
	}
	// IPv4 first: the router's tunnels go out over IPv4.
	for _, a := range addrs {
		if ip, err := netip.ParseAddr(a); err == nil && ip.Is4() {
			return net.JoinHostPort(ip.String(), port), nil
		}
	}
	return net.JoinHostPort(addrs[0], port), nil
}

// ParseConf reads the file; lookup resolves server names (nil: the system's).
func ParseConf(r io.Reader, lookup func(string) ([]string, error)) (*Conf, error) {
	if lookup == nil {
		lookup = net.LookupHost
	}
	var dev, peers strings.Builder
	c := &Conf{}
	section, n, havePriv, peerCount := "", 0, false, 0
	var peerHasKey bool
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 64*1024), 64*1024)
	for sc.Scan() {
		n++
		line := strings.TrimSpace(strings.TrimSuffix(sc.Text(), "\r"))
		if line == "" || line[0] == '#' || line[0] == ';' {
			continue
		}
		if line[0] == '[' {
			switch strings.ToLower(line) {
			case "[interface]":
				section = "interface"
			case "[peer]":
				if section == "peer" && !peerHasKey {
					return nil, &confError{n, "a [Peer] without PublicKey"}
				}
				section, peerHasKey = "peer", false
				peerCount++
			default:
				return nil, &confError{n, "unknown section " + line}
			}
			continue
		}
		k, v, ok := strings.Cut(line, "=")
		if !ok {
			return nil, &confError{n, "not a setting"}
		}
		key := strings.ToLower(strings.TrimSpace(k))
		val := strings.TrimSpace(v)
		switch section {
		case "interface":
			switch {
			case key == "privatekey":
				h, ok := keyHex(val)
				if !ok {
					return nil, &confError{n, "PrivateKey is not a key"}
				}
				fmt.Fprintf(&dev, "private_key=%s\n", h)
				havePriv = true
			case key == "headerprotectionkey":
				h, ok := keyHex(val)
				if !ok {
					return nil, &confError{n, "HeaderProtectionKey is not a key"}
				}
				fmt.Fprintf(&dev, "header_protection_key=%s\n", h)
			case ifaceRange[key] != "":
				if !validRange(val) {
					return nil, &confError{n, strings.TrimSpace(k) + " is not a number or range"}
				}
				fmt.Fprintf(&dev, "%s=%s\n", ifaceRange[key], cleanRange(val))
			case ifaceText[key] != "":
				if strings.ContainsAny(val, "\n") {
					return nil, &confError{n, strings.TrimSpace(k) + " is broken"}
				}
				if val != "" {
					fmt.Fprintf(&dev, "%s=%s\n", ifaceText[key], val)
				}
			case ifaceBool[key] != "":
				b, err := strconv.ParseBool(strings.ToLower(val))
				if err != nil {
					return nil, &confError{n, strings.TrimSpace(k) + " is not true or false"}
				}
				fmt.Fprintf(&dev, "%s=%t\n", ifaceBool[key], b)
			case key == "mtu":
				m, err := strconv.Atoi(val)
				if err != nil || m < 576 || m > 9000 {
					return nil, &confError{n, "MTU is not between 576 and 9000"}
				}
				c.MTU = m
			case key == "address":
				for _, a := range strings.Split(val, ",") {
					a = strings.TrimSpace(a)
					if a == "" {
						continue
					}
					p, err := netip.ParsePrefix(a)
					if err != nil {
						ip, err2 := netip.ParseAddr(a)
						if err2 != nil {
							return nil, &confError{n, "Address is not an address"}
						}
						p = netip.PrefixFrom(ip, ip.BitLen())
					}
					c.Addresses = append(c.Addresses, p)
				}
			case ifaceHost[key]:
			default:
				return nil, &confError{n, "unknown setting " + strings.TrimSpace(k)}
			}
		case "peer":
			switch key {
			case "publickey":
				h, ok := keyHex(val)
				if !ok {
					return nil, &confError{n, "PublicKey is not a key"}
				}
				if peerHasKey {
					return nil, &confError{n, "two PublicKey lines in one [Peer]"}
				}
				fmt.Fprintf(&peers, "public_key=%s\n", h)
				peerHasKey = true
			case "presharedkey":
				h, ok := keyHex(val)
				if !ok || !peerHasKey {
					return nil, &confError{n, "PresharedKey is not a key or comes before PublicKey"}
				}
				fmt.Fprintf(&peers, "preshared_key=%s\n", h)
			case "endpoint":
				if !peerHasKey {
					return nil, &confError{n, "Endpoint comes before PublicKey"}
				}
				ep, err := resolve(val, lookup)
				if err != nil {
					return nil, &confError{n, "Endpoint: " + err.Error()}
				}
				fmt.Fprintf(&peers, "endpoint=%s\n", ep)
				c.Endpoints = append(c.Endpoints, ep)
			case "allowedips":
				if !peerHasKey {
					return nil, &confError{n, "AllowedIPs comes before PublicKey"}
				}
				for _, a := range strings.Split(val, ",") {
					a = strings.TrimSpace(a)
					if a == "" {
						continue
					}
					if _, err := netip.ParsePrefix(a); err != nil {
						return nil, &confError{n, "AllowedIPs has a bad entry"}
					}
					fmt.Fprintf(&peers, "allowed_ip=%s\n", a)
				}
			case "persistentkeepalive":
				if !peerHasKey {
					return nil, &confError{n, "PersistentKeepalive comes before PublicKey"}
				}
				if strings.EqualFold(val, "off") {
					val = "0"
				}
				if !validRange(val) {
					return nil, &confError{n, "PersistentKeepalive is not a number or range"}
				}
				fmt.Fprintf(&peers, "persistent_keepalive_interval=%s\n", cleanRange(val))
			default:
				return nil, &confError{n, "unknown setting " + strings.TrimSpace(k)}
			}
		default:
			return nil, &confError{n, "a setting outside [Interface] or [Peer]"}
		}
	}
	if err := sc.Err(); err != nil {
		return nil, &confError{0, "the file cannot be read"}
	}
	if !havePriv {
		return nil, &confError{0, "no PrivateKey in [Interface]"}
	}
	if peerCount == 0 || !peerHasKey {
		return nil, &confError{0, "no [Peer] with PublicKey"}
	}
	c.UAPI = dev.String() + "replace_peers=true\n" + peers.String()
	return c, nil
}
