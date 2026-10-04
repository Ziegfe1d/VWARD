// vward-ed25519: checks an Ed25519 signature, nothing else, for VWARD's update engine on a
// router whose openssl cannot (Entware's 3.5.5 crashes on MIPS, Viva 2026-10-04).
//   vward-ed25519 verify PUBLIC.pem MESSAGE SIGNATURE
// PUBLIC.pem: an Ed25519 public key (SubjectPublicKeyInfo, as openssl writes it);
// SIGNATURE: the 64 raw bytes. Exit 0: valid; 1: not valid; 2: wrong use or unreadable.
const std = @import("std");
const Ed25519 = std.crypto.sign.Ed25519;

fn readAll(alloc: std.mem.Allocator, path: []const u8, max: usize) ![]u8 {
    return std.fs.cwd().readFileAlloc(alloc, path, max);
}

fn publicKey(alloc: std.mem.Allocator, pem: []const u8) ![32]u8 {
    var b64 = std.ArrayList(u8).init(alloc);
    defer b64.deinit();
    var it = std.mem.tokenizeAny(u8, pem, "\r\n");
    var inside = false;
    while (it.next()) |line| {
        if (std.mem.startsWith(u8, line, "-----BEGIN PUBLIC KEY-----")) {
            inside = true;
        } else if (std.mem.startsWith(u8, line, "-----END PUBLIC KEY-----")) {
            break;
        } else if (inside) {
            try b64.appendSlice(std.mem.trim(u8, line, " \t"));
        }
    }
    const dec = std.base64.standard.Decoder;
    const n = dec.calcSizeForSlice(b64.items) catch return error.BadKey;
    if (n != 44) return error.BadKey;
    var der: [44]u8 = undefined;
    dec.decode(&der, b64.items) catch return error.BadKey;
    // SEQUENCE { SEQUENCE { OID 1.3.101.112 } BIT STRING (0 unused) 32 bytes }
    const prefix = [_]u8{ 0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00 };
    if (!std.mem.eql(u8, der[0..12], &prefix)) return error.BadKey;
    return der[12..44].*;
}

pub fn main() u8 {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const alloc = arena.allocator();
    const args = std.process.argsAlloc(alloc) catch return 2;
    if (args.len != 5 or !std.mem.eql(u8, args[1], "verify")) {
        std.io.getStdErr().writeAll("usage: vward-ed25519 verify PUBLIC.pem MESSAGE SIGNATURE\n") catch {};
        return 2;
    }
    const pem = readAll(alloc, args[2], 4096) catch return 2;
    const msg = readAll(alloc, args[3], 16 * 1024 * 1024) catch return 2;
    const sig_raw = readAll(alloc, args[4], 128) catch return 2;
    if (sig_raw.len != 64) return 1;
    const key_bytes = publicKey(alloc, pem) catch return 2;
    const key = Ed25519.PublicKey.fromBytes(key_bytes) catch return 1;
    const sig = Ed25519.Signature.fromBytes(sig_raw[0..64].*);
    sig.verify(msg, key) catch return 1;
    std.io.getStdOut().writeAll("Signature Verified Successfully\n") catch {};
    return 0;
}
