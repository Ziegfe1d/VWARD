// Package rci talks to Keenetic's RCI on 127.0.0.1:79 directly: one HTTP request per
// read or per batch of commands, no ndmc process. A minimal HTTP/1.1 client (no
// net/http: a smaller static binary for MIPS) with a hard read-only mode: in read-only
// mode only GET and «show ...» parse commands leave the process.
package rci

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
	"sync/atomic"
	"time"
)

type Client struct {
	Addr     string        // host:port, default 127.0.0.1:79
	Timeout  time.Duration // per request
	ReadOnly bool
	Calls    atomic.Int64
	Bytes    atomic.Int64
}

var ErrReadOnly = errors.New("rci: write refused in read-only mode")

func New(addr string, readOnly bool) *Client {
	if addr == "" {
		addr = "127.0.0.1:79"
	}
	return &Client{Addr: addr, Timeout: 30 * time.Second, ReadOnly: readOnly}
}

// Get returns the body of GET /rci/PATH (PATH without the leading /rci/).
func (c *Client) Get(path string) ([]byte, error) {
	return c.do("GET", "/rci/"+strings.TrimPrefix(path, "/"), nil)
}

// Result of one command of a batch.
type Result struct {
	Command string
	Status  string // "ok", "error", "" (no status given: Keenetic says nothing on success)
	Message string
	Raw     json.RawMessage
}

// Parse sends commands as ONE request: POST /rci/ [{"parse":"..."},...]. Keenetic answers
// HTTP 200 either way; a refused command carries status "error" in its element.
func (c *Client) Parse(cmds []string) ([]Result, error) {
	if c.ReadOnly {
		for _, cmd := range cmds {
			if !IsShow(cmd) {
				return nil, fmt.Errorf("%w: %q", ErrReadOnly, cmd)
			}
		}
	}
	type p struct {
		Parse string `json:"parse"`
	}
	req := make([]p, len(cmds))
	for i, cmd := range cmds {
		if strings.ContainsAny(cmd, "\r\n") {
			return nil, fmt.Errorf("rci: newline in command %q", cmd)
		}
		req[i] = p{cmd}
	}
	body, _ := json.Marshal(req)
	out, err := c.do("POST", "/rci/", body)
	if err != nil {
		return nil, err
	}
	var raw []json.RawMessage
	if err := json.Unmarshal(out, &raw); err != nil {
		return nil, fmt.Errorf("rci: answer is not an array: %v", err)
	}
	if len(raw) != len(cmds) {
		return nil, fmt.Errorf("rci: %d answers for %d commands", len(raw), len(cmds))
	}
	res := make([]Result, len(cmds))
	for i := range raw {
		res[i] = Result{Command: cmds[i], Raw: raw[i]}
		res[i].Status, res[i].Message = statusOf(raw[i])
	}
	return res, nil
}

// statusOf finds the worst status anywhere in an answer element (Keenetic nests
// {"status":[{"status":"error","message":...}]} at various depths).
func statusOf(raw json.RawMessage) (string, string) {
	var v any
	if json.Unmarshal(raw, &v) != nil {
		return "error", "unparsable answer"
	}
	st, msg := "", ""
	var walk func(any)
	walk = func(x any) {
		switch t := x.(type) {
		case map[string]any:
			if s, ok := t["status"].(string); ok {
				if s == "error" || (st == "" && s != "") {
					st = s
					if m, ok := t["message"].(string); ok {
						msg = m
					}
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

// IsShow: a command that only reads.
func IsShow(cmd string) bool {
	f := strings.Fields(cmd)
	return len(f) > 0 && f[0] == "show"
}

func (c *Client) do(method, path string, body []byte) ([]byte, error) {
	if c.ReadOnly && method != "GET" && body != nil {
		// Parse() already checked every command; anything else is refused here.
		if method != "POST" || path != "/rci/" {
			return nil, ErrReadOnly
		}
	}
	c.Calls.Add(1)
	conn, err := net.DialTimeout("tcp", c.Addr, c.Timeout)
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(c.Timeout))
	var b bytes.Buffer
	fmt.Fprintf(&b, "%s %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\nAccept: application/json\r\n", method, path, c.Addr)
	if body != nil {
		fmt.Fprintf(&b, "Content-Type: application/json\r\nContent-Length: %d\r\n", len(body))
	}
	b.WriteString("\r\n")
	b.Write(body)
	if _, err := conn.Write(b.Bytes()); err != nil {
		return nil, err
	}
	out, err := readResponse(bufio.NewReader(conn))
	c.Bytes.Add(int64(len(out)))
	return out, err
}

func readResponse(r *bufio.Reader) ([]byte, error) {
	status, err := r.ReadString('\n')
	if err != nil {
		return nil, err
	}
	f := strings.Fields(status)
	if len(f) < 2 {
		return nil, fmt.Errorf("rci: bad status line %q", status)
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
	var body []byte
	switch {
	case chunked:
		for {
			line, err := r.ReadString('\n')
			if err != nil {
				return nil, err
			}
			n, err := strconv.ParseInt(strings.TrimSpace(strings.SplitN(line, ";", 2)[0]), 16, 64)
			if err != nil {
				return nil, fmt.Errorf("rci: bad chunk %q", line)
			}
			if n == 0 {
				break
			}
			chunk := make([]byte, n+2)
			if _, err := io.ReadFull(r, chunk); err != nil {
				return nil, err
			}
			body = append(body, chunk[:n]...)
		}
	case length >= 0:
		body = make([]byte, length)
		if _, err := io.ReadFull(r, body); err != nil {
			return nil, err
		}
	default:
		body, err = io.ReadAll(r)
		if err != nil {
			return nil, err
		}
	}
	if code != 200 {
		return body, fmt.Errorf("rci: HTTP %d", code)
	}
	return body, nil
}
