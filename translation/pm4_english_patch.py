#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Princess Maker 4 -- English translation patcher.

This writes the English translation into your own copy of the game. It contains no
game data: the English text, the offsets it goes to and the line numbers it
replaces, and nothing else. You need an installed copy of the Japanese PC release.

    python pm4_english_patch.py                 patch the game in this folder
    python pm4_english_patch.py --game C:\PM4   patch the game somewhere else
    python pm4_english_patch.py --verify-only   check, change nothing
    python pm4_english_patch.py --restore       put the Japanese back

Your original archive is copied to script.orig_backup before anything is written,
and an existing backup is never overwritten.

------------------------------------------------------------------------------
HOW IT WORKS, for the curious

The game keeps its whole script in one file called "script", a "GCEX" archive of
seven entries. Three of them hold text we care about: room.g2, which is the
compiled story bytecode with every line of dialogue inside it, and item_nam.txt
and item_msg.txt, which are plain Shift-JIS lists of the item names and their
descriptions.

Each entry is stored as a chain of blocks. "GCE1" blocks are compressed with the
game's own LZP codec; "GCE0" blocks are stored uncompressed. The loader accepts
either, so this patcher unpacks the three entries it needs, rewrites them, and
stores them back as GCE0 -- which is why a patched archive is about 2.5 MB
instead of 1.2 MB. The other four entries are copied through byte for byte and
never even unpacked.

Inside room.g2 every string is lightly scrambled:

    stored[i] = (plain[i] + i + length) mod 256

Undoing that is the same arithmetic backwards. The strings are reached by offsets
recorded elsewhere in the bytecode, so a string cannot change length -- move one
byte and every reference after it points into the middle of something. English
therefore has to fit in the bytes the Japanese occupied, and is padded with
spaces. Japanese costs two bytes a character, which is what makes this possible
at all: twenty Japanese characters buy forty of English.

Finally the archive index is rebuilt with the new sizes and its crc32 fixed, and
every entry of the result is unpacked again and checked before anything at all is
installed.
------------------------------------------------------------------------------
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import struct
import sys
import zlib

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Two different "here", and they must not be confused.
#
# Built as a single .exe, this program unpacks itself into a temporary folder and
# runs from there. The patch data travels inside the .exe and must be read from
# that temporary folder -- but the GAME has to be looked for next to the .exe the
# person actually double-clicked, which is somewhere else entirely. Reading both
# from the same place would make the patcher hunt for Princess Maker 4 inside its
# own unpacking directory and never find it.
if getattr(sys, "frozen", False):
    HERE = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE = getattr(sys, "_MEIPASS", HERE)
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
    BUNDLE = HERE
PATCH_JSON = os.path.join(BUNDLE, "pm4_english_patch.json")

# How to tell the reader to run this program again. The two builds are started
# differently, and a message that names the Python file is no help at all to
# somebody who downloaded the .exe precisely because they have no Python.
ME = ('"%s"' % os.path.basename(sys.executable)) if getattr(sys, "frozen", False)      else "python pm4_english_patch.py"

ARCHIVE = "script"
BACKUP = "script.orig_backup"

IDX_MAGIC = b"GCE3"
IDX_CRC_OFF = 0x14
ENT_SIZE = 32
ENT_UNC = 0x10
ENT_STORED = 0x18
DATA_START = 0x10

# The game's chain loop reads each block into a malloc(0x40020) buffer, so that
# is a hard ceiling on one block's payload. 0x40000 is the size the game's own
# room.g2 was authored in and leaves 32 bytes spare.
BLOCK_MAX = 0x40020
CHUNK = 0x40000

TEXT_ENTRIES = ("room.g2", "item_nam.txt", "item_msg.txt")


class Problem(Exception):
    """Something the person running this needs to know, said plainly and
    without a traceback."""


# --------------------------------------------------------------------------- #
# the string transform inside room.g2
# --------------------------------------------------------------------------- #

def scramble(plain):
    n = len(plain)
    return bytes((plain[i] + i + n) & 0xFF for i in range(n))


def unscramble(buf):
    n = len(buf)
    return bytes((buf[i] - i - n) & 0xFF for i in range(n))


# --------------------------------------------------------------------------- #
# GCE0: stored blocks
# --------------------------------------------------------------------------- #

def gce0_blocks(data, chunk=CHUNK):
    """`data` as one or more chained GCE0 blocks, ready to be an archive entry.

    A GCE0 block is the magic, a uint32 length, then that many raw bytes.
    """
    data = bytes(data)
    if not data:
        raise Problem("tried to store an empty entry")
    out = bytearray()
    for i in range(0, len(data), chunk):
        piece = data[i:i + chunk]
        out += b"GCE0" + struct.pack("<I", len(piece)) + piece
    return bytes(out)


# --------------------------------------------------------------------------- #
# GCE1: the game's LZP codec, unpacking only
# --------------------------------------------------------------------------- #

class BitReader:
    """MSB-first inside each byte, the way the game reads it."""

    def __init__(self, data):
        self.d = data
        self.p = 0
        self.avail = 0
        self.cur = 0

    def bit(self):
        if self.avail == 0:
            if self.p >= len(self.d):
                raise Problem("the compressed bit stream ran out early")
            self.cur = self.d[self.p]
            self.p += 1
            self.avail = 8
        self.avail -= 1
        return (self.cur >> self.avail) & 1

    def bits(self, n):
        v = 0
        for _ in range(n):
            v = (v << 1) | self.bit()
        return v

    def gamma(self):
        """Count the zeros before the first 1 bit, then read that many less one
        more bits: a near-Elias-gamma code."""
        k = 0
        while k < 32:
            if self.bit():
                break
            k += 1
        if k <= 1:
            return k
        return (1 << (k - 1)) | self.bits(k - 1)


def block_size(blob, off):
    """-> (magic, uncompressed size, stored size) of the block at `off`."""
    magic = bytes(blob[off:off + 4])
    if magic == b"GCE0":
        n = struct.unpack_from("<I", blob, off + 4)[0]
        return magic, n, 8 + n
    if magic == b"GCE1":
        unc, _zero, lit_len, _dup, ctl_len = struct.unpack_from("<5I", blob, off + 4)
        return magic, unc, 0x18 + lit_len + ctl_len
    raise Problem("a data block starts with %r, which the game would reject. "
                  "This does not look like a Princess Maker 4 script archive."
                  % (magic,))


def decode_block(blob, off):
    """One GCE0 or GCE1 block -> its bytes.

    The LZP side carries no match offset: it is predicted from a 16-bit hash of
    the last two bytes written, so a match is a length alone.
    """
    magic = bytes(blob[off:off + 4])
    if magic == b"GCE0":
        n = struct.unpack_from("<I", blob, off + 4)[0]
        return bytes(blob[off + 8:off + 8 + n])
    unc, _zero, lit_len, _dup, ctl_len = struct.unpack_from("<5I", blob, off + 4)
    lit = blob[off + 0x18:off + 0x18 + lit_len]
    ctl = blob[off + 0x18 + lit_len:off + 0x18 + lit_len + ctl_len]
    if unc <= 0:
        return b""
    out = bytearray()
    br = BitReader(ctl)
    table = [-1] * (1 << 16)
    h = 0
    li = 0
    while True:
        for _ in range(br.gamma()):
            if li >= len(lit):
                raise Problem("the literal stream ran out early")
            b = lit[li]
            li += 1
            table[h] = len(out)
            out.append(b)
            h = ((h & 0xFF) << 8) | b
        if len(out) >= unc:
            break
        m = br.gamma() + 1              # the match-length bias the game sets
        pos = table[h]
        if pos < 0 or pos > len(out):
            raise Problem("the compressed data points at a position that does "
                          "not exist yet; the archive looks damaged")
        for _ in range(m):
            b = out[pos]
            pos += 1
            table[h] = len(out)
            out.append(b)
            h = ((h & 0xFF) << 8) | b
        if len(out) >= unc:
            break
    return bytes(out)


def decode_entry(blob, unc):
    """A whole entry, block after block, the way the game's chain loop does it.

    That loop counts down and stops at exactly zero, so the blocks must sum to
    exactly the size the index records -- an overshoot would hang the game.
    """
    out = bytearray()
    off = 0
    nblk = 0
    while len(out) < unc:
        if off + 8 > len(blob):
            raise Problem("ran out of blocks with %d of %d bytes unpacked"
                          % (len(out), unc))
        _magic, n, size = block_size(blob, off)
        if n == 0:
            raise Problem("a zero-length block would hang the game")
        if n > BLOCK_MAX:
            raise Problem("a block of %d bytes would overrun the game's 0x%x "
                          "buffer" % (n, BLOCK_MAX))
        out += decode_block(blob, off)
        off += size
        nblk += 1
    if len(out) != unc:
        raise Problem("the blocks add up to %d bytes but the index says %d"
                      % (len(out), unc))
    return bytes(out), nblk


# --------------------------------------------------------------------------- #
# the archive
# --------------------------------------------------------------------------- #

def index_crc(idx_bytes):
    """The archive's one checksum: crc32 of the index with +0x14 zeroed."""
    t = bytearray(idx_bytes)
    struct.pack_into("<I", t, IDX_CRC_OFF, 0)
    return zlib.crc32(bytes(t)) & 0xFFFFFFFF


def parse_archive(blob, where):
    """Pull a GCEX archive apart into everything needed to put it back.

        +0x00  "GCEX"
        +0x04  uint32  0
        +0x08  uint64  offset of the index
        +0x10  entry data, back to back in index order

    An entry's offset is not stored anywhere: it is 0x10 plus the running total
    of the stored sizes before it.
    """
    if blob[:4] != b"GCEX":
        raise Problem("%s is not the game's script archive -- it starts with "
                      "%r, not 'GCEX'." % (where, bytes(blob[:4])))
    if len(blob) < 0x30:
        raise Problem("%s is far too small to be the script archive." % where)
    idx_off = struct.unpack_from("<Q", blob, 8)[0]
    if idx_off > len(blob) - 0x20:
        raise Problem("%s is truncated or damaged." % where)
    idx = blob[idx_off:]
    if idx[:4] != IDX_MAGIC:
        raise Problem("the archive index of %s is %r, not %r. A different "
                      "release of the game?"
                      % (where, bytes(idx[:4]), IDX_MAGIC))
    _flags, idx_size = struct.unpack_from("<II", idx, 4)
    idx = idx[:idx_size]
    crc_stored = struct.unpack_from("<I", idx, IDX_CRC_OFF)[0]
    count = struct.unpack_from("<I", idx, 0x18)[0]
    if not 0 < count < 1000:
        raise Problem("%s claims %d entries, which cannot be right." % (where, count))

    ents = []
    for i in range(count):
        b = 0x20 + i * ENT_SIZE
        ents.append({
            "raw": bytearray(idx[b:b + ENT_SIZE]),
            "unc": struct.unpack_from("<Q", idx, b + ENT_UNC)[0],
            "stored": struct.unpack_from("<Q", idx, b + ENT_STORED)[0],
        })
    names_blob = idx[0x20 + count * ENT_SIZE:]
    q = 0
    for e in ents:
        ln = struct.unpack_from("<H", names_blob, q)[0]
        q += 2
        e["name"] = names_blob[q:q + ln].decode("ascii", "replace")
        q += ln

    off = DATA_START
    for e in ents:
        e["offset"] = off
        e["data"] = blob[off:off + e["stored"]]
        if len(e["data"]) != e["stored"]:
            raise Problem("entry %s runs past the end of %s" % (e["name"], where))
        off += e["stored"]
    if off != idx_off:
        raise Problem("in %s the entry data ends at %d but the index starts at "
                      "%d" % (where, off, idx_off))
    return {"size": len(blob), "idx_off": idx_off, "idx_size": idx_size,
            "idx_hdr": idx[:0x20], "crc_stored": crc_stored,
            "names_blob": names_blob, "ents": ents}


def read_archive(path):
    return parse_archive(io.open(path, "rb").read(), os.path.basename(path))


def build_archive(arch, replacements):
    """replacements: {name: (stored_blob, uncompressed_size)}.

    Entries not named are copied through byte for byte -- they are never
    unpacked and repacked, so nothing can go wrong with them. The index gets
    the new sizes, the index crc32 is recomputed, and the index offset in the
    file header is corrected.
    """
    body = bytearray()
    sizes = []
    for e in arch["ents"]:
        blob, unc = replacements.get(e["name"], (e["data"], e["unc"]))
        sizes.append((len(blob), unc))
        body += blob

    idx = bytearray(arch["idx_hdr"])
    for e, (stored, unc) in zip(arch["ents"], sizes):
        r = bytearray(e["raw"])
        struct.pack_into("<Q", r, ENT_UNC, unc)
        struct.pack_into("<Q", r, ENT_STORED, stored)
        idx += r
    idx += arch["names_blob"]
    if len(idx) != arch["idx_size"]:
        raise Problem("the rebuilt index came out %d bytes and the original was "
                      "%d" % (len(idx), arch["idx_size"]))
    struct.pack_into("<I", idx, IDX_CRC_OFF, index_crc(idx))

    out = bytearray(b"GCEX")
    out += struct.pack("<I", 0)
    out += struct.pack("<Q", DATA_START + len(body))
    out += body
    out += idx
    return bytes(out)


# --------------------------------------------------------------------------- #
# finding the game
# --------------------------------------------------------------------------- #

def looks_like_game(folder):
    return os.path.isfile(os.path.join(folder, ARCHIVE))


def find_game(given, _asked=False):
    if given:
        folder = os.path.abspath(given)
        if not os.path.isdir(folder):
            raise Problem("there is no folder called %s" % folder)
        if not looks_like_game(folder):
            raise Problem("%s has no file called 'script' in it, so it is not "
                          "the Princess Maker 4 folder.\nPoint --game at the "
                          "folder that holds PrincessMaker4.exe." % folder)
        return folder
    for cand in (HERE, os.path.dirname(HERE)):
        if looks_like_game(cand):
            return cand
    if _asked:
        raise Problem("still no game folder, so nothing was done.")
    print("I could not find the game by myself.")
    print()
    print("Put this patcher in your Princess Maker 4 folder -- the one with")
    print("PrincessMaker4.exe and a file called 'script' in it -- or type the")
    print("path to that folder here.")
    print()
    try:
        answer = input("Princess Maker 4 folder: ").strip().strip('"').strip("'")
    except EOFError:
        answer = ""
    if not answer:
        raise Problem("no folder given, so nothing was done.\nYou can also say: "
                      "python pm4_english_patch.py --game \"C:\\path\\to\\PM4\"")
    return find_game(answer, _asked=True)


# --------------------------------------------------------------------------- #
# the patching itself
# --------------------------------------------------------------------------- #

def patch_room(room, lines):
    """Write the English into room.g2.

    Every line has to fit the slot the Japanese occupied, because the bytecode
    reaches it by a fixed offset. The English in the patch file is already
    padded to the exact length, and anything that is not is refused rather than
    squeezed in.
    """
    data = bytearray(room)
    written = 0
    for rec in lines:
        off, n, text = rec["off"], rec["len"], rec["en"]
        try:
            plain = text.encode("ascii")
        except UnicodeEncodeError:
            raise Problem("the English for offset %d is not plain ASCII; the "
                          "patch file is damaged." % off)
        if len(plain) != n:
            raise Problem("the English for offset %d is %d bytes but its slot "
                          "is %d bytes. Refusing to write it -- that would move "
                          "everything after it and break the game."
                          % (off, len(plain), n))
        if off + n > len(data):
            raise Problem("offset %d is past the end of room.g2 (%d bytes). "
                          "This is not the release this patch was made for."
                          % (off, len(data)))
        data[off:off + n] = scramble(plain)
        written += 1
    return bytes(data), written


def patch_lines(blob, replacements, name):
    """Replace chosen lines of a Shift-JIS text file, by line number."""
    try:
        rows = blob.decode("cp932").split("\r\n")
    except UnicodeDecodeError:
        raise Problem("%s is not readable as Shift-JIS, so this is not the "
                      "release this patch was made for." % name)
    written = 0
    for key in sorted(replacements, key=int):
        i = int(key)
        if i >= len(rows):
            raise Problem("%s has %d lines but the patch wants to change line "
                          "%d. This is not the release this patch was made for."
                          % (name, len(rows), i))
        rows[i] = replacements[key]
        written += 1
    try:
        return "\r\n".join(rows).encode("cp932"), written
    except UnicodeEncodeError:
        raise Problem("a line of %s cannot be written back as Shift-JIS; the "
                      "patch file is damaged." % name)


def load_patch():
    if not os.path.isfile(PATCH_JSON):
        raise Problem("pm4_english_patch.json is missing.\nIt belongs in the "
                      "same folder as this script -- unzip the whole patch "
                      "together, not just the one file.")
    try:
        with io.open(PATCH_JSON, encoding="utf-8") as f:
            p = json.load(f)
    except ValueError as exc:
        raise Problem("pm4_english_patch.json is damaged (%s).\nDownload the "
                      "patch again." % exc)
    if p.get("format") != 1:
        raise Problem("that patch file says it is format %r, and this patcher "
                      "only knows format 1." % p.get("format"))
    for key in ("source_sha1", "counts", "result_sha1", "room.g2", "items"):
        if key not in p:
            raise Problem("pm4_english_patch.json is incomplete (no %r).\n"
                          "Download the patch again." % key)
    return p


def describe_mismatch(got, patch):
    print("The 'script' file in your game folder is not the one this patch was")
    print("made for.")
    print()
    print("   yours      sha1 %s" % got)
    print("   expected   sha1 %s" % patch["source_sha1"])
    print()
    if got == patch.get("patched_sha1"):
        print("Good news, though: that is exactly the already-patched archive.")
        print("Your game is translated. There is nothing to do.")
        print()
        print("To go back to Japanese:  %s --restore" % ME)
        return
    print("The likely reasons, in order:")
    print()
    print("  1. It is already patched -- by this patch or by another one. If")
    print("     there is a script.orig_backup beside it, run --restore first")
    print("     and then patch again.")
    print("  2. It is a different release of the game. This patch is for the")
    print("     Japanese PC release and depends on exact byte offsets, so it")
    print("     cannot be applied blind to another one.")
    print("  3. The file is damaged. Reinstalling will fix that.")
    print()
    print("If you know what you are doing and want to try anyway, add --force.")
    print("Expect it to fail, and keep your backup.")


def verify_result(blob, patch, where="the rebuilt archive"):
    """Unpack every entry of the finished archive and check that the three we
    changed hold exactly what was intended."""
    arch = parse_archive(blob, where)
    want = patch["result_sha1"]
    ok = True
    for e in arch["ents"]:
        try:
            plain, nblk = decode_entry(e["data"], e["unc"])
        except Problem as exc:
            ok = False
            print("   FAILED  %-13s %s" % (e["name"], exc))
            continue
        if e["name"] in want:
            same = hashlib.sha1(plain).hexdigest() == want[e["name"]]
            ok = ok and same
            print("   %s %-13s %7d bytes in %2d block(s) -- %s"
                  % ("ok     " if same else "FAILED ", e["name"], len(plain),
                     nblk, "holds the English"
                     if same else "NOT what the patch intended"))
        else:
            print("   ok      %-13s %7d bytes in %2d block(s) -- untouched"
                  % (e["name"], len(plain), nblk))
    if index_crc(blob[arch["idx_off"]:]) != arch["crc_stored"]:
        print("   FAILED  the index checksum of the rebuilt archive is wrong")
        ok = False
    else:
        print("   ok      the archive index and its checksum recompute")
    return ok


def install(dest, blob):
    try:
        with io.open(dest, "wb") as f:
            f.write(blob)
    except PermissionError:
        raise Problem(
            "I cannot write to 'script' because something is holding it open.\n"
            "\n"
            "That is almost always Princess Maker 4 itself. Close the game and\n"
            "run this again. Nothing has been changed.")
    except OSError as exc:
        raise Problem("I could not write to 'script': %s\nNothing has been "
                      "changed." % (exc.strerror or exc))


def do_restore(game):
    live = os.path.join(game, ARCHIVE)
    backup = os.path.join(game, BACKUP)
    if not os.path.isfile(backup):
        # Not an error: the translation was never installed here, or it has
        # already been taken off. Raising made the orchestrator print a
        # traceback and the word FAILED for a run in which nothing was
        # wrong. 2 means "there was nothing to do".
        print("   there is no %s here, so the English story was never" % BACKUP)
        print("   installed in this folder, or has already been removed.")
        print("   Leaving '%s' alone." % ARCHIVE)
        return 2
    blob = io.open(backup, "rb").read()
    try:
        parse_archive(blob, BACKUP)
    except Problem as exc:
        raise Problem("the backup does not look like a valid script archive "
                      "(%s), so I will not install it over your game." % exc)
    install(live, blob)
    print("Put your original Japanese script back (%d bytes)." % len(blob))
    print("The backup is still there, so you can patch again whenever you like.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="pm4_english_patch.py",
        description="Install the English translation of Princess Maker 4 into "
                    "your own copy of the game.")
    ap.add_argument("--game", default=None, metavar="FOLDER",
                    help="your Princess Maker 4 folder (default: this one, or "
                         "the one above it)")
    ap.add_argument("--verify-only", action="store_true",
                    help="do everything except install; change nothing")
    ap.add_argument("--restore", action="store_true",
                    help="put the original Japanese script back")
    ap.add_argument("--force", action="store_true",
                    help="patch even though the archive is not the expected one")
    a = ap.parse_args(argv)

    print("Princess Maker 4 -- English translation patcher")
    print("=" * 66)

    game = find_game(a.game)
    print("game folder    %s" % game)

    if a.restore:
        return do_restore(game)

    patch = load_patch()
    c = patch["counts"]
    print("this patch     %d story lines, %d item names, %d item descriptions"
          % (c["room_lines"], c["item_nam_lines"], c["item_msg_lines"]))

    live = os.path.join(game, ARCHIVE)
    try:
        blob = io.open(live, "rb").read()
    except PermissionError:
        raise Problem("I cannot read 'script' because something is holding it "
                      "open.\n\nThat is almost always Princess Maker 4 itself. "
                      "Close the game and run\nthis again. Nothing has been "
                      "changed.")
    got = hashlib.sha1(blob).hexdigest()
    print("your script    %d bytes, sha1 %s" % (len(blob), got))

    if got == patch.get("patched_sha1"):
        # Already translated, which is not a failure and must not be
        # reported as one. Anyone who runs the installer twice -- because
        # a later part of it failed the first time, or simply to be sure
        # -- should be told the story is done, not that something went
        # wrong with it.
        print()
        print("This is already the translated script. Nothing to do.")
        print("To go back to Japanese:  %s --restore" % ME)
        return 0

    if got != patch["source_sha1"]:
        print()
        describe_mismatch(got, patch)
        if not a.force:
            return 1
        print()
        print("--force given, so carrying on anyway.")

    arch = parse_archive(blob, ARCHIVE)
    print("archive        %d entries, index at %d"
          % (len(arch["ents"]), arch["idx_off"]))
    names = [e["name"] for e in arch["ents"]]
    for name in TEXT_ENTRIES:
        if name not in names:
            raise Problem("this archive has no %s in it, so it is not the "
                          "script this patch knows how to translate." % name)

    print()
    print("Unpacking the three entries that hold text...")
    plain = {}
    for e in arch["ents"]:
        if e["name"] in TEXT_ENTRIES:
            plain[e["name"]], nblk = decode_entry(e["data"], e["unc"])
            print("   %-13s %7d bytes from %2d %r block(s)"
                  % (e["name"], len(plain[e["name"]]), nblk,
                     bytes(e["data"][:4])))

    print()
    print("Writing the English in...")
    new = {}
    room, n = patch_room(plain["room.g2"], patch["room.g2"])
    new["room.g2"] = room
    print("   room.g2       %d places written, still %d bytes -- every line fits"
          % (n, len(room)))
    for name in ("item_nam.txt", "item_msg.txt"):
        out, n = patch_lines(plain[name], patch["items"][name], name)
        new[name] = out
        print("   %-13s %d lines replaced, %d bytes (was %d)"
              % (name, n, len(out), len(plain[name])))

    print()
    print("Rebuilding the archive...")
    repl = {name: (gce0_blocks(new[name]), len(new[name]))
            for name in TEXT_ENTRIES}
    built = build_archive(arch, repl)
    print("   %d bytes, up from %d. The three rewritten entries are stored" %
          (len(built), len(blob)))
    print("   uncompressed, which is the whole of that difference; the game")
    print("   reads either kind.")

    print()
    print("Checking the result before touching your game...")
    if not verify_result(built, patch):
        raise Problem("the rebuilt archive did not check out, so it will NOT be "
                      "installed.\nYour game is exactly as it was.")

    if a.verify_only:
        print()
        print("--verify-only, so nothing was installed. It all checks out:")
        print("run the same command without --verify-only to patch the game.")
        return 0

    backup = os.path.join(game, BACKUP)
    print()
    if os.path.isfile(backup):
        print("backup         %s is already there; leaving it untouched." % BACKUP)
    elif got == patch["source_sha1"]:
        shutil.copy2(live, backup)
        print("backup         kept your original as %s (%d bytes)"
              % (BACKUP, os.path.getsize(backup)))
    else:
        # Only ever call something "your original" when it IS the original.
        # With --force on an archive we do not recognise, copying it to
        # script.orig_backup would hand you a backup of the wrong thing -- and
        # if that archive was already English, the Japanese would be gone for
        # good, with --restore quietly restoring English ever after.
        other = os.path.join(game, "script.before_patch")
        shutil.copy2(live, other)
        print("backup         this is not the archive the patch was made for, so")
        print("               it was NOT saved as %s. A copy of exactly what" % BACKUP)
        print("               was there is in script.before_patch instead.")

    install(live, built)
    print("installed      'script' is now the English script")

    print()
    print("=" * 66)
    print("Done. Start Princess Maker 4 the way you normally do. Nothing has to")
    print("run alongside it -- the English is in the game's own files now.")
    print()
    print("To go back to Japanese:  %s --restore" % ME)
    print()
    print("This was free and stays free. If it was worth something to you,")
    print("there is a tip jar at https://ko-fi.com/jdksnoozer -- it buys you")
    print("nothing, which is rather the point.")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Problem as exc:
        print()
        print(exc)
        sys.exit(1)
    except KeyboardInterrupt:
        print()
        print("Stopped. Nothing was changed.")
        sys.exit(1)
