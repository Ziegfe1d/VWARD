//! vward-fetch: VWARD's own download program, in place of Entware's curl (owner, 2026-10-15:
//! curl crashed in libnghttp2 on the Viva, other people's packages carry no guarantee).
//!
//! Only what VWARD asks of curl: HTTP/1.1 GET (HTTPS with TLS 1.3, and 1.2 with RSA
//! certificates, of Zig's own std.crypto; no OpenSSL, no HTTP/2), a time limit, the way out through one interface, a fixed address
//! instead of DNS, a file, the answer's code and time. The options are curl's, so callers keep
//! their command lines; anything else is refused with curl's «not supported» (2).
//!
//!   vward-fetch [-o FILE] [-D FILE] [-w FORMAT] [-f] [-L] [-s] [-S] [-k] [-4]
//!               [-m SECONDS] [--connect-timeout SECONDS] [--interface NAME]
//!               [--resolve HOST:PORT:ADDRESS] [-A AGENT] [-H HEADER] [--max-filesize BYTES]
//!               [--retry N] [--cacert FILE] URL
//!
//! Exit codes are curl's: 0 done, 2 not supported, 3 bad URL, 6 name not resolved, 7 no
//! connection, 22 HTTP error with -f, 23 write error, 28 time is up, 35 TLS failed,
//! 47 too many redirects, 56 receive failed, 60 certificate not trusted, 63 file too big.
const std = @import("std");
const posix = std.posix;
const linux = std.os.linux;
const tls = std.crypto.tls;
const Certificate = std.crypto.Certificate;

const CA_FILES = [_][]const u8{
    "/opt/etc/ssl/certs/ca-certificates.crt",
    "/opt/etc/ssl/cert.pem",
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/ssl/cert.pem",
};

const Opts = struct {
    url: []const u8 = "",
    output: ?[]const u8 = null,
    dump_header: ?[]const u8 = null,
    write_out: ?[]const u8 = null,
    fail: bool = false,
    follow: bool = false,
    show_error: bool = false,
    silent: bool = false,
    insecure: bool = false,
    max_time: u32 = 0,
    connect_timeout: u32 = 0,
    interface: ?[]const u8 = null,
    resolve: ?[]const u8 = null,
    agent: []const u8 = "vward-fetch/1",
    headers: std.ArrayList([]const u8),
    max_filesize: u64 = 0,
    retry: u32 = 0,
    cacert: ?[]const u8 = null,
};

const Fail = error{ Usage, BadUrl, Resolve, Connect, Timeout, Tls, Cert, Recv, Write, TooBig, Redirects, Http };

fn code(e: anyerror) u8 {
    return switch (e) {
        error.Usage => 2,
        error.BadUrl => 3,
        error.Resolve => 6,
        error.Connect => 7,
        error.Http => 22,
        error.Write => 23,
        error.Timeout => 28,
        error.Tls => 35,
        error.Redirects => 47,
        error.Recv => 56,
        error.Cert => 60,
        error.TooBig => 63,
        else => 56,
    };
}

var g_show_error = true;

fn say(comptime fmt: []const u8, args: anytype) void {
    if (!g_show_error) return;
    std.io.getStdErr().writer().print("vward-fetch: " ++ fmt ++ "\n", args) catch {};
}

// The whole run has a time limit (-m): the timer ends it with curl's 28.
fn onAlarm(_: i32) callconv(.c) void {
    std.io.getStdErr().writeAll("vward-fetch: time is up\n") catch {};
    linux.exit_group(28);
}

fn armTimer(seconds: u32) void {
    if (seconds == 0) return;
    var act = posix.Sigaction{ .handler = .{ .handler = onAlarm }, .mask = posix.empty_sigset, .flags = 0 };
    posix.sigaction(posix.SIG.ALRM, &act, null);
    const t = linux.itimerspec{ .it_interval = .{ .sec = 0, .nsec = 0 }, .it_value = .{ .sec = @intCast(seconds), .nsec = 0 } };
    _ = linux.setitimer(@intFromEnum(linux.ITIMER.REAL), &t, null);
}

fn parseSeconds(s: []const u8) Fail!u32 {
    const f = std.fmt.parseFloat(f64, s) catch return error.Usage;
    if (f < 0 or f > 86400) return error.Usage;
    return @intFromFloat(@ceil(f));
}

fn parseArgs(alloc: std.mem.Allocator, args: []const []const u8) Fail!Opts {
    var o = Opts{ .headers = std.ArrayList([]const u8).init(alloc) };
    var i: usize = 1;
    while (i < args.len) : (i += 1) {
        const a = args[i];
        const next = struct {
            fn get(as: []const []const u8, j: *usize) Fail![]const u8 {
                j.* += 1;
                if (j.* >= as.len) return error.Usage;
                return as[j.*];
            }
        }.get;
        if (a.len > 1 and a[0] == '-' and a[1] != '-') {
            // Short options, alone or together («-fsS»); the last may take a value.
            var k: usize = 1;
            while (k < a.len) : (k += 1) {
                switch (a[k]) {
                    'f' => o.fail = true,
                    's' => o.silent = true,
                    'S' => o.show_error = true,
                    'L' => o.follow = true,
                    'k' => o.insecure = true,
                    '4' => {},
                    'o', 'D', 'w', 'm', 'A', 'H' => {
                        const v = if (k + 1 < a.len) a[k + 1 ..] else try next(args, &i);
                        switch (a[k]) {
                            'o' => o.output = v,
                            'D' => o.dump_header = v,
                            'w' => o.write_out = v,
                            'm' => o.max_time = try parseSeconds(v),
                            'A' => o.agent = v,
                            'H' => o.headers.append(v) catch return error.Usage,
                            else => unreachable,
                        }
                        break;
                    },
                    else => return error.Usage,
                }
            }
        } else if (std.mem.eql(u8, a, "--output")) {
            o.output = try next(args, &i);
        } else if (std.mem.eql(u8, a, "--dump-header")) {
            o.dump_header = try next(args, &i);
        } else if (std.mem.eql(u8, a, "--write-out")) {
            o.write_out = try next(args, &i);
        } else if (std.mem.eql(u8, a, "--max-time")) {
            o.max_time = try parseSeconds(try next(args, &i));
        } else if (std.mem.eql(u8, a, "--connect-timeout")) {
            o.connect_timeout = try parseSeconds(try next(args, &i));
        } else if (std.mem.eql(u8, a, "--interface")) {
            o.interface = try next(args, &i);
        } else if (std.mem.eql(u8, a, "--resolve")) {
            o.resolve = try next(args, &i);
        } else if (std.mem.eql(u8, a, "--user-agent")) {
            o.agent = try next(args, &i);
        } else if (std.mem.eql(u8, a, "--header")) {
            o.headers.append(try next(args, &i)) catch return error.Usage;
        } else if (std.mem.eql(u8, a, "--max-filesize")) {
            o.max_filesize = std.fmt.parseInt(u64, try next(args, &i), 10) catch return error.Usage;
        } else if (std.mem.eql(u8, a, "--retry")) {
            o.retry = std.fmt.parseInt(u32, try next(args, &i), 10) catch return error.Usage;
        } else if (std.mem.eql(u8, a, "--cacert")) {
            o.cacert = try next(args, &i);
        } else if (std.mem.eql(u8, a, "--fail")) {
            o.fail = true;
        } else if (std.mem.eql(u8, a, "--location")) {
            o.follow = true;
        } else if (std.mem.eql(u8, a, "--silent")) {
            o.silent = true;
        } else if (std.mem.eql(u8, a, "--show-error")) {
            o.show_error = true;
        } else if (std.mem.eql(u8, a, "--insecure")) {
            o.insecure = true;
        } else if (std.mem.eql(u8, a, "--proto") or std.mem.eql(u8, a, "--noproxy") or
            std.mem.eql(u8, a, "--retry-delay") or std.mem.eql(u8, a, "--max-redirs"))
        {
            _ = try next(args, &i); // what curl needs these for is how vward-fetch works anyway
        } else if (std.mem.eql(u8, a, "--http1.1") or std.mem.eql(u8, a, "--tlsv1.2") or
            std.mem.eql(u8, a, "--tlsv1.3") or std.mem.eql(u8, a, "--ipv4") or
            std.mem.eql(u8, a, "--compressed") or std.mem.eql(u8, a, "--globoff"))
        {} else if (a.len > 0 and a[0] != '-') {
            if (o.url.len != 0) return error.Usage;
            o.url = a;
        } else return error.Usage;
    }
    if (o.url.len == 0) return error.Usage;
    g_show_error = !o.silent or o.show_error;
    return o;
}

const Url = struct { https: bool, host: []const u8, port: u16, path: []const u8 };

fn parseUrl(u: []const u8) Fail!Url {
    var rest: []const u8 = undefined;
    var https = false;
    if (std.mem.startsWith(u8, u, "https://")) {
        https = true;
        rest = u[8..];
    } else if (std.mem.startsWith(u8, u, "http://")) {
        rest = u[7..];
    } else return error.BadUrl;
    const slash = std.mem.indexOfScalar(u8, rest, '/') orelse rest.len;
    const hostport = rest[0..slash];
    const path = if (slash < rest.len) rest[slash..] else "/";
    if (hostport.len == 0 or std.mem.indexOfScalar(u8, hostport, '@') != null) return error.BadUrl;
    var host = hostport;
    var port: u16 = if (https) 443 else 80;
    if (std.mem.lastIndexOfScalar(u8, hostport, ':')) |c| {
        host = hostport[0..c];
        port = std.fmt.parseInt(u16, hostport[c + 1 ..], 10) catch return error.BadUrl;
    }
    if (host.len == 0) return error.BadUrl;
    return .{ .https = https, .host = host, .port = port, .path = path };
}

fn address(alloc: std.mem.Allocator, o: *const Opts, u: Url) Fail!std.net.Address {
    // --resolve HOST:PORT:ADDRESS: this host is reached at this address (the route engine's
    // check of one IP through one interface).
    if (o.resolve) |r| {
        var it = std.mem.splitScalar(u8, r, ':');
        const h = it.next() orelse return error.Usage;
        const p = it.next() orelse return error.Usage;
        const ip = it.rest();
        const pn = std.fmt.parseInt(u16, p, 10) catch return error.Usage;
        if (std.ascii.eqlIgnoreCase(h, u.host) and pn == u.port)
            return std.net.Address.parseIp4(ip, u.port) catch return error.Usage;
    }
    if (std.net.Address.parseIp4(u.host, u.port)) |a| return a else |_| {}
    const list = std.net.getAddressList(alloc, u.host, u.port) catch return error.Resolve;
    for (list.addrs) |a| if (a.any.family == posix.AF.INET) return a;
    return error.Resolve;
}

fn setTimeout(fd: posix.socket_t, opt: u32, seconds: u32) void {
    const tv = posix.timeval{ .sec = @intCast(seconds), .usec = 0 };
    posix.setsockopt(fd, posix.SOL.SOCKET, opt, std.mem.asBytes(&tv)) catch {};
}

fn connect(o: *const Opts, addr: std.net.Address) Fail!std.net.Stream {
    const fd = posix.socket(posix.AF.INET, posix.SOCK.STREAM | posix.SOCK.CLOEXEC, 0) catch return error.Connect;
    errdefer posix.close(fd);
    if (o.interface) |ifname| {
        // The way out through one interface (the provider or a tunnel), as curl --interface.
        posix.setsockopt(fd, posix.SOL.SOCKET, posix.SO.BINDTODEVICE, ifname) catch return error.Connect;
    }
    const ct = if (o.connect_timeout != 0) o.connect_timeout else 30;
    setTimeout(fd, posix.SO.SNDTIMEO, ct);
    posix.connect(fd, &addr.any, addr.getOsSockLen()) catch |e| return switch (e) {
        error.WouldBlock, error.ConnectionTimedOut => error.Timeout,
        else => error.Connect,
    };
    // Reads and writes: the whole time limit, or a minute without a byte.
    const io = if (o.max_time != 0) o.max_time else 60;
    setTimeout(fd, posix.SO.SNDTIMEO, io);
    setTimeout(fd, posix.SO.RCVTIMEO, io);
    return .{ .handle = fd };
}

const Conn = struct {
    stream: std.net.Stream,
    tls_client: ?tls.Client = null,

    fn read(c: *Conn, buf: []u8) Fail!usize {
        if (c.tls_client) |*t| {
            return t.read(c.stream, buf) catch |e| switch (e) {
                error.WouldBlock => error.Timeout,
                else => error.Recv,
            };
        }
        return c.stream.read(buf) catch |e| switch (e) {
            error.WouldBlock => error.Timeout,
            else => error.Recv,
        };
    }

    fn writeAll(c: *Conn, bytes: []const u8) Fail!void {
        if (c.tls_client) |*t| return t.writeAll(c.stream, bytes) catch error.Recv;
        c.stream.writeAll(bytes) catch return error.Recv;
    }

    fn close(c: *Conn) void {
        c.stream.close();
    }
};

fn tlsError(e: anyerror) Fail {
    const name = @errorName(e);
    if (std.mem.startsWith(u8, name, "Certificate") or std.mem.eql(u8, name, "TlsCertificateNotVerified")) return error.Cert;
    if (e == error.WouldBlock) return error.Timeout;
    return error.Tls;
}

const Result = struct { status: u16 = 0, location: ?[]u8 = null, bytes: u64 = 0 };

fn exchange(alloc: std.mem.Allocator, o: *const Opts, u: Url, bundle: ?Certificate.Bundle, out: std.fs.File, hdr: ?std.fs.File) Fail!Result {
    const addr = try address(alloc, o, u);
    var conn = Conn{ .stream = try connect(o, addr) };
    defer conn.close();
    if (u.https) {
        conn.tls_client = tls.Client.init(conn.stream, .{
            .host = if (o.insecure) .no_verification else .{ .explicit = u.host },
            .ca = if (o.insecure or bundle == null) .no_verification else .{ .bundle = bundle.? },
        }) catch |e| {
            say("TLS with {s}: {s}", .{ u.host, @errorName(e) });
            return tlsError(e);
        };
    }
    var req = std.ArrayList(u8).init(alloc);
    const w = req.writer();
    w.print("GET {s} HTTP/1.1\r\nHost: {s}\r\nUser-Agent: {s}\r\nAccept: */*\r\nConnection: close\r\n", .{ u.path, u.host, o.agent }) catch return error.Write;
    for (o.headers.items) |h| w.print("{s}\r\n", .{h}) catch return error.Write;
    w.writeAll("\r\n") catch return error.Write;
    try conn.writeAll(req.items);

    // The answer's head, up to the empty line (64 KB at most).
    var head = std.ArrayList(u8).init(alloc);
    var buf: [16384]u8 = undefined;
    var body_start: usize = 0;
    while (true) {
        const n = try conn.read(&buf);
        if (n == 0) return error.Recv;
        head.appendSlice(buf[0..n]) catch return error.Recv;
        if (std.mem.indexOf(u8, head.items, "\r\n\r\n")) |e| {
            body_start = e + 4;
            break;
        }
        if (head.items.len > 65536) return error.Recv;
    }
    const head_text = head.items[0..body_start];
    if (hdr) |f| f.writeAll(head_text) catch return error.Write;
    var res = Result{};
    var lines = std.mem.splitSequence(u8, head_text, "\r\n");
    const status_line = lines.next() orelse return error.Recv;
    if (!std.mem.startsWith(u8, status_line, "HTTP/1.")) return error.Recv;
    var sp = std.mem.tokenizeScalar(u8, status_line, ' ');
    _ = sp.next();
    res.status = std.fmt.parseInt(u16, sp.next() orelse return error.Recv, 10) catch return error.Recv;
    var length: ?u64 = null;
    var chunked = false;
    while (lines.next()) |l| {
        const c = std.mem.indexOfScalar(u8, l, ':') orelse continue;
        const name = std.mem.trim(u8, l[0..c], " \t");
        const value = std.mem.trim(u8, l[c + 1 ..], " \t");
        if (std.ascii.eqlIgnoreCase(name, "content-length")) {
            length = std.fmt.parseInt(u64, value, 10) catch null;
        } else if (std.ascii.eqlIgnoreCase(name, "transfer-encoding")) {
            chunked = std.ascii.indexOfIgnoreCase(value, "chunked") != null;
        } else if (std.ascii.eqlIgnoreCase(name, "location")) {
            res.location = alloc.dupe(u8, value) catch null;
        }
    }
    const redirect = o.follow and res.location != null and (res.status == 301 or res.status == 302 or res.status == 303 or res.status == 307 or res.status == 308);
    if (redirect) return res; // the body of a redirect is not wanted
    if (o.fail and res.status >= 400) return error.Http;
    if (o.max_filesize != 0) if (length) |l| if (l > o.max_filesize) return error.TooBig;

    // The body: by its length, in chunks, or up to the end of the connection.
    var reader = BodyReader{ .conn = &conn, .pending = head.items[body_start..] };
    var sink = Sink{ .file = out, .max = o.max_filesize };
    if (chunked) {
        while (true) {
            const size_line = try reader.line(alloc);
            const semi = std.mem.indexOfScalar(u8, size_line, ';') orelse size_line.len;
            const size = std.fmt.parseInt(u64, std.mem.trim(u8, size_line[0..semi], " \t"), 16) catch return error.Recv;
            if (size == 0) break;
            try reader.copy(&sink, size);
            _ = try reader.line(alloc);
        }
    } else if (length) |l| {
        try reader.copy(&sink, l);
    } else {
        try reader.copyToEnd(&sink);
    }
    res.bytes = sink.written;
    return res;
}

const Sink = struct {
    file: std.fs.File,
    max: u64,
    written: u64 = 0,

    fn put(s: *Sink, bytes: []const u8) Fail!void {
        if (s.max != 0 and s.written + bytes.len > s.max) return error.TooBig;
        s.file.writeAll(bytes) catch return error.Write;
        s.written += bytes.len;
    }
};

const BodyReader = struct {
    conn: *Conn,
    pending: []const u8,
    buf: [16384]u8 = undefined,

    fn fill(r: *BodyReader) Fail!bool {
        if (r.pending.len != 0) return true;
        const n = try r.conn.read(&r.buf);
        if (n == 0) return false;
        r.pending = r.buf[0..n];
        return true;
    }

    fn copy(r: *BodyReader, sink: *Sink, len: u64) Fail!void {
        var left = len;
        while (left > 0) {
            if (!try r.fill()) return error.Recv; // cut short
            const take: usize = @intCast(@min(left, r.pending.len));
            try sink.put(r.pending[0..take]);
            r.pending = r.pending[take..];
            left -= take;
        }
    }

    fn copyToEnd(r: *BodyReader, sink: *Sink) Fail!void {
        while (try r.fill()) {
            try sink.put(r.pending);
            r.pending = r.pending[r.pending.len..];
        }
    }

    fn line(r: *BodyReader, alloc: std.mem.Allocator) Fail![]const u8 {
        var acc = std.ArrayList(u8).init(alloc);
        while (true) {
            if (!try r.fill()) return error.Recv;
            if (std.mem.indexOfScalar(u8, r.pending, '\n')) |nl| {
                acc.appendSlice(r.pending[0..nl]) catch return error.Recv;
                r.pending = r.pending[nl + 1 ..];
                return std.mem.trimRight(u8, acc.items, "\r");
            }
            acc.appendSlice(r.pending) catch return error.Recv;
            r.pending = r.pending[r.pending.len..];
            if (acc.items.len > 1024) return error.Recv;
        }
    }
};

fn loadBundle(alloc: std.mem.Allocator, o: *const Opts) ?Certificate.Bundle {
    if (o.insecure) return null;
    var b = Certificate.Bundle{};
    if (o.cacert) |p| {
        b.addCertsFromFilePathAbsolute(alloc, p) catch {
            say("no certificates in {s}", .{p});
            return null;
        };
        return b;
    }
    for (CA_FILES) |p| {
        b.addCertsFromFilePathAbsolute(alloc, p) catch continue;
        if (b.map.count() > 0) return b;
    }
    say("no certificate bundle found", .{});
    return null;
}

fn writeOut(fmt: []const u8, res: Result, seconds: f64) void {
    var out = std.io.getStdOut().writer();
    var i: usize = 0;
    while (i < fmt.len) : (i += 1) {
        if (fmt[i] == '%' and std.mem.startsWith(u8, fmt[i..], "%{")) {
            const end = std.mem.indexOfScalarPos(u8, fmt, i, '}') orelse break;
            const name = fmt[i + 2 .. end];
            if (std.mem.eql(u8, name, "http_code") or std.mem.eql(u8, name, "response_code")) {
                out.print("{d:0>3}", .{res.status}) catch {};
            } else if (std.mem.eql(u8, name, "time_total")) {
                out.print("{d:.6}", .{seconds}) catch {};
            } else if (std.mem.eql(u8, name, "redirect_url")) {
                out.writeAll(res.location orelse "") catch {};
            } else if (std.mem.eql(u8, name, "size_download")) {
                out.print("{d}", .{res.bytes}) catch {};
            }
            i = end;
        } else if (fmt[i] == '\\' and i + 1 < fmt.len and fmt[i + 1] == 'n') {
            out.writeAll("\n") catch {};
            i += 1;
        } else {
            out.writeByte(fmt[i]) catch {};
        }
    }
}

pub fn main() u8 {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const alloc = arena.allocator();
    const args = std.process.argsAlloc(alloc) catch return 2;
    var o = parseArgs(alloc, args) catch |e| {
        say("usage: vward-fetch [curl options] URL (an option it does not have: 2)", .{});
        return code(e);
    };
    armTimer(o.max_time);
    const started = std.time.nanoTimestamp();

    var out = std.io.getStdOut();
    var out_path: ?[]const u8 = null;
    if (o.output) |p| if (!std.mem.eql(u8, p, "-")) {
        out = std.fs.cwd().createFile(p, .{}) catch return 23;
        out_path = p;
    };
    var hdr: ?std.fs.File = null;
    if (o.dump_header) |p| hdr = if (std.mem.eql(u8, p, "-")) std.io.getStdOut() else (std.fs.cwd().createFile(p, .{}) catch return 23);
    const bundle = loadBundle(alloc, &o);

    var url = o.url;
    var res = Result{};
    var hops: u32 = 0;
    var tries: u32 = 0;
    const rc: u8 = blk: while (true) {
        const u = parseUrl(url) catch |e| break :blk code(e);
        if (u.https and !o.insecure and bundle == null) break :blk 77;
        res = exchange(alloc, &o, u, bundle, out, hdr) catch |e| {
            // A retry is for what may pass the next time: no answer, not a refusal.
            if (tries < o.retry and (e == error.Connect or e == error.Timeout or e == error.Recv)) {
                tries += 1;
                std.time.sleep(std.time.ns_per_s);
                if (out_path) |p| out = std.fs.cwd().createFile(p, .{}) catch break :blk 23;
                continue;
            }
            if (e != error.Http) say("{s}: {s}", .{ url, @errorName(e) });
            break :blk code(e);
        };
        if (o.follow and res.location != null and res.status >= 300 and res.status < 400) {
            hops += 1;
            if (hops > 5) break :blk 47;
            const loc = res.location.?;
            if (std.mem.startsWith(u8, loc, "http://") or std.mem.startsWith(u8, loc, "https://")) {
                url = loc;
            } else if (loc.len > 0 and loc[0] == '/') {
                const cur = parseUrl(url) catch break :blk 3;
                url = std.fmt.allocPrint(alloc, "{s}://{s}:{d}{s}", .{ if (cur.https) "https" else "http", cur.host, cur.port, loc }) catch break :blk 2;
            } else break :blk 3;
            continue;
        }
        break :blk 0;
    };
    const seconds = @as(f64, @floatFromInt(std.time.nanoTimestamp() - started)) / std.time.ns_per_s;
    if (o.write_out) |fmt| writeOut(fmt, res, seconds);
    return rc;
}
