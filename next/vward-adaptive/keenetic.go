package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"strconv"
	"strings"
	"time"
)

// Keenetic is what the program needs from the router: the names of one group and
// a way to add and remove one name. Nothing else is ever written.
type Keenetic interface {
	Group(name string) (names []string, routed string, err error)
	Include(group, host string) error
	Exclude(group, host string) error
	Save() error
}

var ErrGroupFull = errors.New("group is full")

// rciClient talks to RCI on 127.0.0.1:79 (HTTP without a password from the router itself).
type rciClient struct {
	addr    string
	timeout time.Duration
}

func (c *rciClient) do(method, path string, body []byte) ([]byte, error) {
	conn, err := net.DialTimeout("tcp", c.addr, c.timeout)
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(c.timeout))
	var b bytes.Buffer
	fmt.Fprintf(&b, "%s %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\nAccept: application/json\r\n", method, path, c.addr)
	if body != nil {
		fmt.Fprintf(&b, "Content-Type: application/json\r\nContent-Length: %d\r\n", len(body))
	}
	b.WriteString("\r\n")
	b.Write(body)
	if _, err := conn.Write(b.Bytes()); err != nil {
		return nil, err
	}
	return readHTTP(bufio.NewReader(conn))
}

func readHTTP(r *bufio.Reader) ([]byte, error) {
	status, err := r.ReadString('\n')
	if err != nil {
		return nil, err
	}
	f := strings.Fields(status)
	if len(f) < 2 {
		return nil, fmt.Errorf("rci: bad status %q", status)
	}
	code, _ := strconv.Atoi(f[1])
	length, chunked := -1, false
	for {
		h, err := r.ReadString('\n')
		if err != nil {
			return nil, err
		}
		h = strings.TrimRight(h, "\r\n")
		if h == "" {
			break
		}
		k, v, _ := strings.Cut(h, ":")
		switch strings.ToLower(strings.TrimSpace(k)) {
		case "content-length":
			length, _ = strconv.Atoi(strings.TrimSpace(v))
		case "transfer-encoding":
			chunked = strings.Contains(strings.ToLower(v), "chunked")
		}
	}
	var out []byte
	switch {
	case chunked:
		var buf bytes.Buffer
		for {
			line, err := r.ReadString('\n')
			if err != nil {
				return nil, err
			}
			n, err := strconv.ParseInt(strings.TrimSpace(strings.SplitN(line, ";", 2)[0]), 16, 64)
			if err != nil || n < 0 || n > 16<<20 {
				return nil, fmt.Errorf("rci: bad chunk %q", line)
			}
			if n == 0 {
				break
			}
			if _, err := io.CopyN(&buf, r, n); err != nil {
				return nil, err
			}
			if _, err := r.ReadString('\n'); err != nil {
				return nil, err
			}
		}
		out = buf.Bytes()
	case length >= 0:
		out = make([]byte, length)
		if _, err := io.ReadFull(r, out); err != nil {
			return nil, err
		}
	default:
		out, err = io.ReadAll(io.LimitReader(r, 16<<20))
		if err != nil {
			return nil, err
		}
	}
	if code != 200 {
		return out, fmt.Errorf("rci: HTTP %d", code)
	}
	return out, nil
}

// parse sends one CLI command; Keenetic answers 200 either way, an error sits in "status".
func (c *rciClient) parse(cmd string) (json.RawMessage, error) {
	if strings.ContainsAny(cmd, "\r\n") {
		return nil, fmt.Errorf("newline in command")
	}
	body, _ := json.Marshal([]map[string]string{{"parse": cmd}})
	out, err := c.do("POST", "/rci/", body)
	if err != nil {
		return nil, err
	}
	var arr []json.RawMessage
	if err := json.Unmarshal(out, &arr); err != nil || len(arr) != 1 {
		return nil, fmt.Errorf("rci: unexpected answer to %q", cmd)
	}
	if st, msg := rciStatus(arr[0]); st == "error" {
		if strings.Contains(msg, "too many") {
			return nil, ErrGroupFull
		}
		return nil, fmt.Errorf("rci: %q: %s", cmd, msg)
	}
	return arr[0], nil
}

func rciStatus(raw json.RawMessage) (string, string) {
	var v any
	if json.Unmarshal(raw, &v) != nil {
		return "error", "unparsable answer"
	}
	st, msg := "", ""
	var walk func(any)
	walk = func(x any) {
		switch t := x.(type) {
		case map[string]any:
			if s, ok := t["status"].(string); ok && (s == "error" || st == "") {
				st = s
				if m, ok := t["message"].(string); ok {
					msg = m
				}
			}
			for _, y := range t {
				walk(y)
			}
		case []any:
			for _, y := range t {
				walk(y)
			}
		}
	}
	walk(v)
	return st, msg
}

func (c *rciClient) Group(name string) ([]string, string, error) {
	out, err := c.do("GET", "/rci/show/running-config", nil)
	if err != nil {
		return nil, "", err
	}
	var obj struct {
		Message []string `json:"message"`
	}
	var lines []string
	if json.Unmarshal(out, &obj) == nil && len(obj.Message) > 0 {
		lines = obj.Message
	} else if json.Unmarshal(out, &lines) != nil || len(lines) == 0 {
		return nil, "", fmt.Errorf("rci: running-config: unexpected answer")
	}
	names, routed := groupFromConfig(lines, name)
	return names, routed, nil
}

// groupFromConfig: the «include» names of «object-group fqdn NAME» and the target of
// «dns-proxy / route object-group NAME TARGET» in running-config lines.
func groupFromConfig(lines []string, name string) ([]string, string) {
	var names []string
	routed, ctx := "", ""
	for _, line := range lines {
		line = strings.TrimRight(line, "\r")
		if line == "" {
			continue
		}
		f := strings.Fields(line)
		if len(f) == 0 {
			continue
		}
		if line[0] != ' ' && line[0] != '\t' {
			ctx = ""
			switch {
			case len(f) == 3 && f[0] == "object-group" && f[1] == "fqdn" && f[2] == name:
				ctx = "group"
			case len(f) == 1 && f[0] == "dns-proxy":
				ctx = "dns-proxy"
			}
			continue
		}
		switch {
		case ctx == "group" && len(f) == 2 && f[0] == "include":
			names = append(names, strings.ToLower(f[1]))
		case ctx == "dns-proxy" && len(f) >= 4 && f[0] == "route" && f[1] == "object-group" && f[2] == name:
			routed = f[3]
		}
	}
	return names, routed
}

func (c *rciClient) Include(group, host string) error {
	_, err := c.parse("object-group fqdn " + group + " include " + host)
	return err
}

func (c *rciClient) Exclude(group, host string) error {
	_, err := c.parse("no object-group fqdn " + group + " include " + host)
	return err
}

func (c *rciClient) Save() error {
	_, err := c.parse("system configuration save")
	return err
}
