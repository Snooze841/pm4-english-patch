# -*- coding: utf-8 -*-
r"""
Apply the interface translation to a player's own copy of the game.

This is the half of the work that runs on someone else's machine, so it is
written to need nothing but the Python standard library -- no Pillow, no
numpy -- and to leave the game in a state it can be put back from.

WHAT IT DOES NOT CARRY

Not one pixel of the game's artwork. For each label the patch holds two
things: where the label is, and our own lettering with an alpha channel. The
background the lettering sits on is rebuilt here, from the player's own file:

  clear   the label floats on nothing, so the rectangle is set transparent.
          189 of the 507 labels are like this.

  panel   the label sits on a wooden plate. The plate is rebuilt by reading
          the untouched pixel immediately left of the label and the one
          immediately right of it, on each row, and shading between them --
          which meets both neighbours exactly, so no seam can appear -- then
          adding the grain taken from a clean span of the same plate.

WHY IT CAN WRITE IN PLACE

Measured, not assumed. Changing pixels does not change an entry's length, so
no offset moves. The u32 in the index that looks like it might be a checksum
is not one: three pictures already differ from the shipped archive in every
pixel of several rectangles and their index entries are byte-identical, and
the game loads them. So the patcher seeks and writes a few kilobytes instead
of rebuilding 613 MB.

UNDO

Before the first write, the original bytes of every rectangle it is about to
touch are saved to gd.ui_undo -- a few hundred kilobytes of the player's own
file, which never leaves their machine. --undo puts them back.

    python pm4_ui_apply.py --game "C:\Games\Princess Maker 4"
    python pm4_ui_apply.py --game ... --undo
    python pm4_ui_apply.py --game ... --check
"""
import base64
import io
import json
import os
import struct
import sys
import zlib

if getattr(sys, "frozen", False):
    HERE = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE = getattr(sys, "_MEIPASS", HERE)
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
    BUNDLE = HERE
RECIPE = "pm4_ui_patch.json"
UNDO = "gd.ui_undo"
UNDO_MAGIC = b"PM4UIUNDO1"


def find_game(needs):
    """The game folder, looked for rather than assumed.

    The development layout has these scripts in a tools folder beside the
    game, so the game is one level up. The shipped layout has them copied
    INTO the game folder, so the game is right here. Guessing one of the
    two was wrong half the time; checking for the file we need is right
    both times.
    """
    for cand in (HERE, os.path.dirname(HERE)):
        if os.path.exists(os.path.join(cand, needs)):
            return cand
    return None



# ------------------------------------------------------------ the archive
def parse_gcex(path):
    """Entry table of a GCEX archive: name, offset and stored length."""
    with io.open(path, "rb") as f:
        hdr = f.read(16)
        if hdr[:4] != b"GCEX":
            raise ValueError("%s is not a GCEX archive" % path)
        index_at = struct.unpack_from("<I", hdr, 8)[0]
        f.seek(index_at)
        g3 = f.read(32)
        if g3[:4] != b"GCE3":
            raise ValueError("%s has no GCE3 index" % path)
        count = struct.unpack_from("<I", g3, 0x18)[0]
        raw = f.read(count * 32)
        ents = []
        for i in range(count):
            ents.append({
                "unc": struct.unpack_from("<Q", raw, i * 32 + 0x10)[0],
                "stored": struct.unpack_from("<Q", raw, i * 32 + 0x18)[0],
            })
        rest = f.read()
    p = 0
    for e in ents:
        ln = struct.unpack_from("<H", rest, p)[0]
        p += 2
        e["name"] = rest[p:p + ln].decode("shift-jis", "replace")
        p += ln
    off = 0x10
    for e in ents:
        e["offset"] = off
        off += e["stored"]
    return ents


def read_picture(f, entry):
    """
    Return (width, height, bytearray of BGRA pixels, kind, extra) for one
    entry, for the two kinds of picture this archive holds.

    The interface windows are raw BGRA with a sixteen-byte header. The
    name-entry screens are ordinary 24-bit BMP files, stored bottom row
    first with each row padded to a multiple of four bytes. Rather than
    carry two sets of editing routines, a BMP is unpacked into the same
    top-down BGRA buffer everything else uses and packed back afterwards,
    so clearing, rebuilding and stamping work on both without knowing which
    they have.
    """
    f.seek(entry["offset"])
    head = f.read(54)
    if head[:4] == b"BGRA":
        w, h = struct.unpack_from("<II", head, 8)
        if 16 + w * h * 4 != entry["stored"]:
            return None
        # 54 bytes were read to sniff the format, which is past this one's
        # 16-byte header, so go back before taking the pixels
        f.seek(entry["offset"] + 16)
        # keep the header too: what gets written back is the whole entry,
        # not just its pixels -- writing pixels at the entry's start would
        # put them over the header and destroy the picture
        return w, h, bytearray(f.read(w * h * 4)), "bgra", head[:16]

    if head[:2] == b"BM":
        pix_at = struct.unpack_from("<I", head, 10)[0]
        w, h = struct.unpack_from("<ii", head, 18)
        bpp = struct.unpack_from("<H", head, 28)[0]
        comp = struct.unpack_from("<I", head, 30)[0]
        if bpp != 24 or comp != 0 or w <= 0:
            return None
        flip = h > 0
        h = abs(h)
        stride = (w * 3 + 3) & ~3
        f.seek(entry["offset"])
        whole = bytearray(f.read(entry["stored"]))
        buf = bytearray(w * h * 4)
        for y in range(h):
            sy = (h - 1 - y) if flip else y
            row = pix_at + sy * stride
            o = y * w * 4
            for x in range(w):
                i = row + x * 3
                buf[o] = whole[i]
                buf[o + 1] = whole[i + 1]
                buf[o + 2] = whole[i + 2]
                buf[o + 3] = 255
                o += 4
        return w, h, buf, "bmp", (whole, pix_at, stride, flip)

    return None


def pack_picture(w, h, buf, kind, extra):
    """The bytes to write back, for either kind of picture."""
    if kind == "bgra":
        return bytes(extra) + bytes(buf)
    whole, pix_at, stride, flip = extra
    for y in range(h):
        sy = (h - 1 - y) if flip else y
        row = pix_at + sy * stride
        o = y * w * 4
        for x in range(w):
            i = row + x * 3
            whole[i] = buf[o]
            whole[i + 1] = buf[o + 1]
            whole[i + 2] = buf[o + 2]
            o += 4
    return bytes(whole)


# ------------------------------------------------------- rebuilding plates
def smooth(vals, k=3):
    n = len(vals)
    out = []
    run = 0.0
    for i in range(n):
        lo, hi = max(0, i - k), min(n, i + k + 1)
        out.append(sum(vals[lo:hi]) / float(hi - lo))
    return out


def px(buf, w, x, y):
    i = (y * w + x) * 4
    return buf[i], buf[i + 1], buf[i + 2], buf[i + 3]


def setpx(buf, w, x, y, bgra):
    i = (y * w + x) * 4
    buf[i] = bgra[0]
    buf[i + 1] = bgra[1]
    buf[i + 2] = bgra[2]
    buf[i + 3] = bgra[3]


def clear_rect(buf, w, h, rect):
    x0, y0, rw, rh = rect
    for y in range(y0, y0 + rh):
        for x in range(x0, x0 + rw):
            setpx(buf, w, x, y, (0, 0, 0, 0))


def rebuild_panel(buf, w, h, rect, donor):
    """
    Shade across the label between its untouched neighbours, then lay the
    plate's grain over the top.

    Interpolating rather than repeating is what removes the seam: the first
    version copied a span from the label's right-hand side across the whole
    rectangle, which ignored the plate's left-to-right shading and left a
    visible vertical join. Meeting both neighbours exactly cannot do that.
    """
    x0, y0, rw, rh = rect

    def solid_neighbour(ay, start, step, limit=6):
        """
        The nearest opaque pixel outward from the label on this row.

        Taking the pixel immediately beside the rectangle is not safe. These
        rectangles are grown a little to swallow the old lettering's soft
        edge, so on a rounded plate they can reach past its rim, where the
        picture is transparent. Interpolating from a transparent neighbour
        fades the plate out: the status window came back with the wood gone
        and the checkerboard showing through. Stepping outward to the first
        opaque pixel finds the plate again.
        """
        c = start
        for _ in range(limit):
            if not (0 <= c < w):
                return None
            q = px(buf, w, c, ay)
            if q[3] > 24:
                return q
            c += step
        return None

    for yy in range(rh):
        ay = y0 + yy
        left = solid_neighbour(ay, x0 - 1, -1)
        right = solid_neighbour(ay, x0 + rw, +1)
        if left is None and right is None:
            continue
        if left is None:
            left = right
        if right is None:
            right = left

        # Grain, but only from a source wide enough and quiet enough to be
        # grain. A narrow donor repeats whatever happens to be in it every
        # few pixels, and if that includes the edge of something it prints a
        # row of little marks across the label -- which is what appeared on
        # the money panel. Below eight pixels, or with swings too large to be
        # wood, the shading is left smooth instead.
        grain = None
        if donor:
            dx, dy, dw, dh, side = donor
            if dw >= 8:
                cols = [px(buf, w, max(0, min(w - 1, dx + i)), ay)
                        for i in range(dw)]
                lum = [(c[0] + c[1] + c[2]) / 3.0 for c in cols]
                base = smooth(lum)
                dev = [lum[i] - base[i] for i in range(dw)]
                if max(abs(v) for v in dev) <= 14:
                    grain = dev

        for xx in range(rw):
            t = (xx + 1) / float(rw + 1)
            g = grain[xx % len(grain)] if grain else 0.0
            out = []
            for ch in range(3):
                v = left[ch] + (right[ch] - left[ch]) * t + g
                out.append(0 if v < 0 else (255 if v > 255 else int(v + 0.5)))
            a = left[3] + (right[3] - left[3]) * t
            a = 0 if a < 0 else (255 if a > 255 else int(a + 0.5))
            setpx(buf, w, x0 + xx, ay, (out[0], out[1], out[2], a))


def mean_ring(buf, w, h, rect, pad=5):
    """The colour of the picture just outside a rectangle."""
    x0, y0, rw, rh = rect
    acc = [0, 0, 0]
    n = 0
    for x in range(x0, x0 + rw):
        for y in (y0 - pad, y0 + rh + pad - 1):
            if 0 <= x < w and 0 <= y < h:
                c = px(buf, w, x, y)
                for i in range(3):
                    acc[i] += c[i]
                n += 1
    for y in range(y0, y0 + rh):
        for x in (x0 - pad, x0 + rw + pad - 1):
            if 0 <= x < w and 0 <= y < h:
                c = px(buf, w, x, y)
                for i in range(3):
                    acc[i] += c[i]
                n += 1
    if not n:
        return [0, 0, 0]
    return [a / float(n) for a in acc]


def copy_patch(buf, w, h, rect, src, tile=None, feather=7, src_buf=None):
    """
    Cover a rectangle with a piece of the picture borrowed from elsewhere.

    This is how the kana come off the name-entry keyboard. The grid has
    several genuinely empty cells, which are clean parchment the player
    already owns, so a kana is covered by a copy of one of those rather than
    by any colour of ours.

    Two corrections make it invisible. The borrowed piece is levelled to the
    paper immediately around where it lands, because the sheet shades across
    its width. And its edges are faded in rather than cut: pasted as hard
    squares, ninety of these read as a checkerboard, since each piece
    carries its own mottling and the straight joins catch the eye even
    though no single piece looks wrong.
    """
    x0, y0, rw, rh = rect
    sx, sy = src[0], src[1]
    # A clean source is usually smaller than the area being covered -- the
    # keyboard's spare parchment comes in single 32-pixel cells, and the
    # button strip is 150 wide. Repeating the clean piece covers the strip
    # without reading past it into the lettering next door.
    tw = tile[0] if tile else rw
    th = tile[1] if tile else rh

    # Read the source from the picture as it was before any of this
    # started, never from the picture being built.
    #
    # The spare cells on the keyboard are spare in the Japanese layout, and
    # several of them are exactly where an English letter now goes. Reading
    # live, an op would copy parchment out of a cell that an earlier op had
    # just written a letter into, and the letter travelled with it: the
    # lowercase rows came out doubled and the button strip became a row of
    # overlapping fragments.
    src_buf = src_buf if src_buf is not None else buf
    want = mean_ring(buf, w, h, rect)
    have = mean_ring(src_buf, w, h, (sx, sy, tw, th))
    shift = [want[i] - have[i] for i in range(3)]

    taken = []
    for y in range(rh):
        row = []
        for x in range(rw):
            c = px(src_buf, w, max(0, min(w - 1, sx + (x % tw))),
                   max(0, min(h - 1, sy + (y % th))))
            row.append(c)
        taken.append(row)

    for y in range(rh):
        for x in range(rw):
            tx, ty = x0 + x, y0 + y
            if not (0 <= tx < w and 0 <= ty < h):
                continue
            edge = min(x, y, rw - 1 - x, rh - 1 - y)
            a = 1.0 if edge >= feather else (edge + 1) / float(feather + 1)
            src_c = taken[y][x]
            dst_c = px(buf, w, tx, ty)
            out = []
            for i in range(3):
                v = src_c[i] + shift[i]
                v = 0 if v < 0 else (255 if v > 255 else v)
                out.append(int(round(v * a + dst_c[i] * (1 - a))))
            setpx(buf, w, tx, ty, (out[0], out[1], out[2], dst_c[3]))


def rebuild_panel_v(buf, w, h, rect, limit=8):
    """
    Rebuild a rectangle by shading DOWN it rather than across it.

    The contest banners have silver ornaments at both ends and the title
    between them, so shading across the title drags the ornaments into it --
    the first attempt left a grey smear where the Japanese had been. Above
    and below the title there is nothing but plate, and the plate's gradient
    runs vertically, so meeting the row above and the row below reproduces
    it and never touches the ornaments at all.
    """
    x0, y0, rw, rh = rect

    def solid(x, start, step):
        c = start
        for _ in range(limit):
            if not (0 <= c < h):
                return None
            q = px(buf, w, x, c)
            if q[3] > 24:
                return q
            c += step
        return None

    for x in range(x0, x0 + rw):
        if not (0 <= x < w):
            continue
        above = solid(x, y0 - 1, -1)
        below = solid(x, y0 + rh, +1)
        if above is None and below is None:
            continue
        if above is None:
            above = below
        if below is None:
            below = above
        for y in range(rh):
            t = (y + 1) / float(rh + 1)
            out = []
            for ch in range(3):
                v = above[ch] + (below[ch] - above[ch]) * t
                out.append(0 if v < 0 else (255 if v > 255 else int(v + 0.5)))
            a = above[3] + (below[3] - above[3]) * t
            a = 0 if a < 0 else (255 if a > 255 else int(a + 0.5))
            setpx(buf, w, x, y0 + y, (out[0], out[1], out[2], a))


def stamp_rect(buf, w, h, rect, rgba):
    """Alpha-composite our lettering (RGBA) onto the picture (BGRA)."""
    x0, y0, rw, rh = rect
    for yy in range(rh):
        for xx in range(rw):
            i = (yy * rw + xx) * 4
            sr, sg, sb, sa = rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3]
            if sa == 0:
                continue
            if sa == 255:
                setpx(buf, w, x0 + xx, y0 + yy, (sb, sg, sr, 255))
                continue
            db, dg, dr, da = px(buf, w, x0 + xx, y0 + yy)
            a = sa / 255.0
            na = sa + da * (1 - a)
            if na <= 0:
                setpx(buf, w, x0 + xx, y0 + yy, (0, 0, 0, 0))
                continue
            def mix(s, d):
                return int((s * sa + d * da * (1 - a)) / na + 0.5)
            setpx(buf, w, x0 + xx, y0 + yy,
                  (mix(sb, db), mix(sg, dg), mix(sr, dr), int(na + 0.5)))


# ------------------------------------------------------------------ files
def load_recipe(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_undo(path, blocks):
    """blocks: list of (entry name, offset, original bytes)."""
    out = bytearray(UNDO_MAGIC)
    out += struct.pack("<I", len(blocks))
    for name, off, data in blocks:
        nb = name.encode("utf-8")
        out += struct.pack("<H", len(nb)) + nb
        out += struct.pack("<QI", off, len(data))
        out += data
    with io.open(path, "wb") as f:
        f.write(zlib.compress(bytes(out), 6))


def load_undo(path):
    with io.open(path, "rb") as f:
        raw = zlib.decompress(f.read())
    if raw[:len(UNDO_MAGIC)] != UNDO_MAGIC:
        raise ValueError("not an undo file written by this patcher")
    p = len(UNDO_MAGIC)
    n = struct.unpack_from("<I", raw, p)[0]
    p += 4
    out = []
    for _ in range(n):
        ln = struct.unpack_from("<H", raw, p)[0]
        p += 2
        name = raw[p:p + ln].decode("utf-8")
        p += ln
        off, size = struct.unpack_from("<QI", raw, p)
        p += 12
        out.append((name, off, raw[p:p + size]))
        p += size
    return out


# ------------------------------------------------------------------- main
def table_already_latin(game):
    """Whether this copy's name-entry keys already type Latin letters.

    The pictures of the keys must agree with the table that says what they
    type, in both directions: painting letters on a kana table lies, and so
    does repainting kana over a table that was changed to letters. Asking
    the keyboard module keeps the two in step whichever command is run.
    """
    try:
        import pm4_exe_keyboard
        return pm4_exe_keyboard.keyboard_is_installed(game)
    except Exception:
        return False


def do_patch(game, recipe, check_only, with_keyboard=False):
    archive = os.path.join(game, "gd")
    if not os.path.exists(archive):
        print("   no 'gd' archive in %s" % game)
        return 1

    ents = {e["name"]: e for e in parse_gcex(archive)}
    # The name-entry keyboard's pictures only make sense alongside the
    # character table inside PrincessMaker4.exe. Painting A-Z on the keys
    # while the table still holds kana gives a keyboard that shows one
    # letter and types another, so they are left out unless the caller has
    # patched the table too.
    held_back = set(recipe.get("keyboard_pictures") or ())
    if with_keyboard or table_already_latin(game):
        held_back = set()
    todo = []
    for name, spec in recipe["entries"].items():
        if name in held_back:
            continue
        e = ents.get(name)
        if not e:
            print("   %-22s not in this archive -- skipped" % name)
            continue
        todo.append((name, e, spec))
    if held_back:
        print("   the %d name-entry keyboard picture(s) are left in Japanese,"
              % len(held_back))
        print("   because the keys would otherwise show letters the game")
        print("   does not type. \"Add the English keyboard.bat\" does both.")

    if not todo:
        print("   nothing to do")
        return 1

    print("   %d interface picture(s) to translate" % len(todo))
    if check_only:
        with io.open(archive, "rb") as f:
            for name, e, spec in todo:
                got = read_picture(f, e)
                state = "unreadable"
                if got:
                    w, h = got[0], got[1]
                    state = ("%dx%d %s, matches the recipe" % (w, h, got[3])
                             if [w, h] == spec["size"]
                             else "%dx%d but the recipe expects %dx%d"
                                  % (w, h, spec["size"][0], spec["size"][1]))
                print("      %-22s %s" % (name, state))
        return 0

    undo_path = os.path.join(game, UNDO)

    # If this has been run here before, put the originals back first.
    #
    # Patching an already-patched archive is not harmless. The keyboard is
    # rebuilt by borrowing blank parchment from the spare cells of the
    # player's own grid, and after one pass several of those cells hold a
    # letter -- so a second pass would copy letters where it meant to copy
    # paper. Starting from the originals every time also means the result
    # does not depend on how many times anyone pressed the button.
    if os.path.exists(undo_path):
        print("   this was patched before; putting the originals back first")
        rc = do_undo(game, quiet=True)
        if rc != 0:
            print("   could not undo the earlier patch, so nothing was done")
            return 1
        # and throw the old undo away, so a fresh one is written covering
        # whatever this version of the patch touches. An undo file left over
        # from an earlier release would list fewer pictures than the patch
        # now changes, and the ones it did not list could never be put back.
        try:
            os.remove(undo_path)
        except OSError:
            print("   could not clear the old undo file; stopping")
            return 1

    blocks = []
    changed = 0
    with io.open(archive, "r+b") as f:
        for name, e, spec in todo:
            got = read_picture(f, e)
            if not got:
                print("      %-22s not a plain picture -- skipped" % name)
                continue
            w, h, buf, kind, extra = got
            if [w, h] != spec["size"]:
                print("      %-22s is %dx%d, recipe expects %dx%d -- skipped"
                      % (name, w, h, spec["size"][0], spec["size"][1]))
                continue

            if not os.path.exists(undo_path):
                f.seek(e["offset"])
                blocks.append((name, e["offset"], f.read(e["stored"])))

            # a snapshot to borrow from, so no op can copy another op's work
            orig = bytes(buf)
            for it in spec["items"]:
                rect = tuple(it["rect"])
                mode = it["erase"]
                if mode == "clear":
                    clear_rect(buf, w, h, rect)
                elif mode == "panelv":
                    rebuild_panel_v(buf, w, h, rect)
                elif mode == "copy":
                    copy_patch(buf, w, h, rect, it["source"], it.get("tile"),
                               src_buf=orig)
                elif mode == "none":
                    pass
                else:
                    rebuild_panel(buf, w, h, rect, it["donor"])
                if not it.get("stamp"):
                    continue
                rgba = zlib.decompress(base64.b64decode(it["stamp"]))
                # Where the lettering goes is not always where the old
                # lettering was. On the town map a single kanji occupies far
                # less width than the English name replacing it, so the
                # erase stays narrow -- it has to, the plate either side is
                # the only thing left to rebuild from -- while the word is
                # set across the whole signboard.
                stamp_rect(buf, w, h, tuple(it.get("stamp_rect") or rect), rgba)

            out = pack_picture(w, h, buf, kind, extra)
            if len(out) != e["stored"]:
                print("      %-22s would change length %d -> %d -- skipped"
                      % (name, e["stored"], len(out)))
                continue
            f.seek(e["offset"])
            f.write(out)
            changed += 1
            print("      %-22s %3d label(s)" % (name, len(spec["items"])))

        # The schedule cards, which need every card at once and so cannot
        # be done entry by entry like the rest.
        cards = recipe.get("cards")
        if cards:
            print("      %-22s %d card(s), rebuilding the banner from them all"
                  % ("sch\\schd*.argb", len(cards["titles"])))
            if not os.path.exists(undo_path):
                for name in cards["titles"]:
                    e = ents.get(name)
                    if e:
                        f.seek(e["offset"])
                        blocks.append((name, e["offset"], f.read(e["stored"])))
            for name, e, frames in do_cards(f, archive, ents, cards):
                changed += 1
                print("      %-22s %d frame(s)" % (name, frames))

        if blocks and not os.path.exists(undo_path):
            save_undo(undo_path, blocks)

    print("   %d picture(s) written; undo saved to %s"
          % (changed, os.path.basename(undo_path)))
    return 0


def build_plaque(f, ents, spec):
    """
    Rebuild the schedule banner's plaque out of the player's own cards.

    The 23 job cards all carry the same ornamented plaque with a different
    job name on it, and none of the erase methods used elsewhere works
    here. Shading across the title drags the scrollwork into streaks,
    because the ornament is inside the span being crossed. Borrowing a
    blank patch is no use either: there is no blank plaque anywhere.

    But the cards can supply it between them. Their titles are different
    widths and shapes, so at any one pixel most cards show plaque and a few
    show lettering, and the value a MAJORITY of them agree on is the
    plaque. No threshold on brightness, which matters because these titles
    are pale green inside a dark green outline -- half of each glyph is
    lighter than the background, so anything keyed on "dark" keeps the
    other half.

    One strip, about fifty pixels wide, is crossed by every title and so
    has no majority either way. That strip is the plain middle of the
    panel, with both ornaments now recovered outside it, so it is shaded
    straight across from its edges -- the method that failed over the whole
    banner is exactly right over this gap.
    """
    fw = spec["frame"]
    top, bottom = spec["top"], spec["bottom"]
    need = spec.get("agree", 12)
    bands = []
    for name in spec["entries"]:
        e = ents.get(name)
        if not e:
            continue
        got = read_picture(f, e)
        if not got:
            continue
        w, h, buf, kind, extra = got
        bands.append([[px(buf, w, x, y) for x in range(fw)]
                      for y in range(top, bottom)])
    if len(bands) < need:
        return None

    hh = bottom - top
    clean = [[None] * fw for _ in range(hh)]
    for y in range(hh):
        for x in range(fw):
            votes = {}
            for b in bands:
                c = b[y][x]
                votes[c] = votes.get(c, 0) + 1
            best = None
            for c, n in votes.items():
                if best is None or n > best[1]:
                    best = (c, n)
            if best and best[1] >= need:
                clean[y][x] = best[0]

    cols = [x for x in range(fw)
            if any(clean[y][x] is None for y in range(hh))]
    if cols:
        x0, x1 = min(cols), max(cols)
        left, right = x0 - 1, x1 + 1
        if 0 <= left and right < fw:
            span = float(right - left)
            for y in range(hh):
                a, b = clean[y][left], clean[y][right]
                if a is None or b is None:
                    continue
                for x in range(x0, x1 + 1):
                    t = (x - left) / span
                    clean[y][x] = tuple(
                        int(round(a[k] + (b[k] - a[k]) * t)) for k in range(4))
    return clean


def title_mask(buf, w, clean, rect, top, spec, tol=18):
    """
    Which pixels of this banner are the Japanese title.

    Everything that differs from the rebuilt plaque is a candidate, but not
    everything that differs is lettering: one card has a bush drawn across
    its banner, and an earlier rule that judged each pixel on its colour
    accepted the bush's soft edge, because a blend of bush over plaque
    points in nearly the same direction as a blend of the title's dark
    outline over plaque. The bush came back with a pale fringe cut around
    it.

    Connectivity settles it without any colour judgement. The title always
    occupies the middle of the banner -- every one of the 23 crosses the
    same central strip -- so the mask is grown outward from there through
    neighbouring pixels that also differ. The bush is not attached to the
    lettering, so it is never reached, and stays exactly as it was.
    """
    rx, ry, rw, rh = rect
    seed_lo = spec.get("seed", [74, 124])[0] - rx
    seed_hi = spec.get("seed", [74, 124])[1] - rx

    def differs(x, y):
        c = clean[ry - top + y][rx + x]
        if c is None:
            return False
        a = px(buf, w, rx + x, ry + y)
        return max(abs(a[i] - c[i]) for i in range(3)) > tol

    mask = [[False] * rw for _ in range(rh)]
    stack = []
    for y in range(rh):
        for x in range(max(0, seed_lo), min(rw, seed_hi + 1)):
            if differs(x, y) and not mask[y][x]:
                mask[y][x] = True
                stack.append((x, y))
    while stack:
        x, y = stack.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                       (1, 1), (1, -1), (-1, 1), (-1, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < rw and 0 <= ny < rh and not mask[ny][nx] \
               and differs(nx, ny):
                mask[ny][nx] = True
                stack.append((nx, ny))
    return mask


def is_lettering(here, plaque, inks, tol=46):
    """
    Is this pixel part of the Japanese title, rather than something else
    drawn over the banner?

    Compositing says a pixel covered by lettering is
        pixel = a * ink + (1 - a) * plaque
    for one of the two colours the titles are painted in. Projecting the
    pixel's departure from the plaque onto each ink's direction gives that
    `a`, and the part of the departure the projection cannot explain says
    whether the answer is believable. A pale title edge over the plaque
    explains well; a bush does not, and is left where it is.
    """
    d = [here[i] - plaque[i] for i in range(3)]
    if max(abs(v) for v in d) <= 10:
        return True                      # already plaque; harmless to set
    for ink in inks:
        g = [ink[i] - plaque[i] for i in range(3)]
        den = sum(v * v for v in g)
        if den == 0:
            continue
        a = sum(d[i] * g[i] for i in range(3)) / float(den)
        if a < -0.1 or a > 1.25:
            continue
        res = sum((d[i] - a * g[i]) ** 2 for i in range(3)) ** 0.5
        if res <= tol:
            return True
    return False


def do_cards(f_in, archive, ents, spec):
    """Translate the schedule cards, all 23 of them, every frame."""
    with io.open(archive, "rb") as f:
        clean = build_plaque(f, ents, spec)
    if clean is None:
        print("      could not rebuild the banner; cards left alone")
        return []

    fw = spec["frame"]
    top = spec["top"]
    rx, ry, rw, rh = spec["paste"]
    done = []
    for name, title in spec["titles"].items():
        e = ents.get(name)
        if not e:
            continue
        got = read_picture(f_in, e)
        if not got:
            continue
        w, h, buf, kind, extra = got
        frames = max(1, w // fw)
        rgba = zlib.decompress(base64.b64decode(title["stamp"]))
        sx, sy, sw, sh = title["rect"]
        # Put the plaque back only over this card's own title.
        #
        # Covering the whole banner is wrong on the one card that has a
        # bush drawn across it: the bush got cut off at the banner's edge.
        # Deciding pixel by pixel on colour left a pale fringe around the
        # bush, because its soft edge points the same way as the title's
        # dark outline. Growing a region outward from the title was worse
        # still -- the title touches the bush, so the whole bush was
        # reached.
        #
        # The rectangle each title occupies is measured when the patch is
        # built, from the pale green no other part of the picture uses, and
        # travels as four numbers like every other rectangle here.
        ex, ey, ew, eh = title.get("erase", [rx, ry, rw, rh])
        for i in range(frames):
            ox = i * fw
            for y in range(eh):
                sy_ = ey - ry + y
                for x in range(ew):
                    c = clean[ey - top + y][ex + x]
                    if c is not None:
                        setpx(buf, w, ox + ex + x, ey + y, c)
            stamp_rect(buf, w, h, (ox + sx, sy, sw, sh), rgba)
        out = pack_picture(w, h, buf, kind, extra)
        if len(out) != e["stored"]:
            print("      %-22s length changed -- skipped" % name)
            continue
        f_in.seek(e["offset"])
        f_in.write(out)
        done.append((name, e, frames))
    return done


def do_undo(game, quiet=False):
    archive = os.path.join(game, "gd")
    undo_path = os.path.join(game, UNDO)
    if not os.path.exists(undo_path):
        if not quiet:
            # 2, not 1: nothing to undo is the ordinary state of a folder
            # the interface patch was never applied to, and reporting it
            # as a failure alarms people for no reason.
            print("   there is no %s here, so the English menus were" % UNDO)
            print("   never installed in this folder, or have already been")
            print("   removed. Leaving the picture archive alone.")
        return 2
    try:
        blocks = load_undo(undo_path)
    except Exception as e:
        print("   the undo file could not be read (%s)" % e)
        return 1
    with io.open(archive, "r+b") as f:
        for name, off, data in blocks:
            f.seek(off)
            f.write(data)
            if not quiet:
                print("      %-22s restored" % name)
    if not quiet:
        print("   %d picture(s) put back" % len(blocks))
    return 0


def main(argv):
    game = None
    mode = "patch"
    with_keyboard = False
    recipe_path = os.path.join(BUNDLE, RECIPE)
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--game" and i + 1 < len(argv):
            game = argv[i + 1]
            i += 1
        elif a == "--recipe" and i + 1 < len(argv):
            recipe_path = argv[i + 1]
            i += 1
        elif a == "--undo":
            mode = "undo"
        elif a == "--check":
            mode = "check"
        elif a == "--with-keyboard":
            with_keyboard = True
        i += 1

    if not game:
        game = find_game("gd")
        if not game:
            print("Princess Maker 4 -- interface translation")
            print("   I could not find the archive 'gd' next to me or one")
            print("   folder up. Tell me where the game is:")
            print("      --game \"C:\\path\\to\\the game\"")
            return 1
    print("Princess Maker 4 -- interface translation")
    print("   game: %s" % game)

    if mode == "undo":
        return do_undo(game)
    if not os.path.exists(recipe_path):
        print("   recipe not found: %s" % recipe_path)
        return 1
    return do_patch(game, load_recipe(recipe_path), mode == "check",
                    with_keyboard)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
