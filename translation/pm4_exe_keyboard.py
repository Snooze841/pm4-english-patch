# -*- coding: utf-8 -*-
r"""
Turn the name-entry keyboard from kana into letters.

Princess Maker 4 lets you name your daughter from a grid of kana and offers
no way to type a Latin name at all. That grid is not drawn from the picture:
the picture only shows what is in a table of character codes inside the
executable, and the code that reads it copies whatever two bytes it finds in
a cell, checking only for 0x8140 -- the full-width space -- which it treats
as an empty cell. It does not care what the bytes mean. So putting letters in
the table puts letters in the game, and pressing a cell then types that
letter.

WHAT WAS MEASURED, AND WHAT WAS NOT

  Found by searching for the kana themselves, not by address arithmetic:
  the hiragana block begins at file offset 0x0ED770 and the katakana block
  at 0x0ED6B0, each six rows of fifteen cp932 characters at stride 0x20.
  An address computed from the published pointer array was tried first and
  pointed at nonsense, so this locates the table by its contents instead --
  which also makes it safe on a differently built copy of the game.

  The rows are stored BOTTOM ROW FIRST. The row at the lowest address is the
  bottom line on screen. Printed and read to be sure, because getting it
  backwards would put the alphabet upside down.

  Full-width Latin is already in the game: it carries its own ASCII to
  full-width table at 0x0EE7D0, and writes names like "Ａｇｅ　１１" into
  its own save files. The letters will render.

  NOT established: whether SafeDisc objects to a changed executable. The
  file is already patched by a no-DVD fix and runs, which is suggestive and
  not proof. If the game refuses to start after this, run --undo; the same
  table can instead be written while the game is running, through the
  dinput hook this project already builds.

THE LAYOUT

  Page 1, which the left button used to switch to hiragana:
      row 0   A B C D E F G H I J K L M
      row 1   N O P Q R S T U V W X Y Z
      row 3   a b c d e f g h i j k l m
      row 4   n o p q r s t u v w x y z
  Page 2, the old katakana page:
      row 0   0 1 2 3 4 5 6 7 8 9
      row 1   - ' . , & ! ?

  Both cases live on one page so an ordinary name needs no switching, and
  the second page keeps the toggle honest rather than leaving it doing
  nothing.

  Six characters per name remains the limit. That check lives in the
  encrypted part of the executable and no edit to the file can reach it.

Run:  python pm4_exe_keyboard.py --game "C:\Games\Princess Maker 4"
      python pm4_exe_keyboard.py --game ... --undo
      python pm4_exe_keyboard.py --game ... --show
"""
import io
import os
import struct
import sys
import time

EXE = "PrincessMaker4.exe"
BACKUP = "PrincessMaker4.exe.kbd_backup"
HERE = os.path.dirname(os.path.abspath(__file__))

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

ROW_STRIDE = 0x20
CELLS = 15
ROWS = 6
DEAD = b"\x81\x40"

# the top row of each block, used to find the block in the file
HIRA_TOP = "あかさたなはまやらわがざだばぱ"
KATA_TOP = "アカサタナハマヤラワガザダバパ"

PAGE1 = {
    0: "ABCDEFGHIJKLM",
    1: "NOPQRSTUVWXYZ",
    3: "abcdefghijklm",
    4: "nopqrstuvwxyz",
}
PAGE2 = {
    0: "0123456789",
    1: "-'.,&!?",
}


def inspect_protection(data):
    """
    Is this executable still guarded by its copy protection?

    It matters because of what happened on somebody else's machine: the
    keyboard patch went in, and the game stopped starting. The 384 bytes
    themselves are harmless; what is not harmless is that Princess Maker 4
    ships behind SafeDisc, which checks the file against itself before
    handing control to the game. Change anything and the check fails.

    On a copy whose protection has already been removed -- a no-CD patch --
    that check never runs and the edit is fine. The difference is visible in
    the file:

      the protection lives in two sections called stxt774 and stxt371;
      a loader patch parks its own code in the empty padding after the PE
      header, which the publisher left as zeros.

    So: zeros in the padding and the sections present means the protection
    is probably still live, and the keyboard patch should not be applied
    without the person knowing what they are risking.

    Returns (protected, notes).
    """
    notes = []
    try:
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        nsec = struct.unpack_from("<H", data, pe + 6)[0]
        opt = struct.unpack_from("<H", data, pe + 20)[0]
        base = pe + 24 + opt
    except Exception:
        # Cannot tell: refuse rather than proceed. A check that carries on
        # when it does not understand the file is worse than no check at
        # all, because it reads as reassurance.
        return True, ["could not read this file's section table, so I cannot "
                      "tell whether its copy protection is active"]

    guards = []
    for i in range(nsec):
        o = base + i * 40
        name = data[o:o + 8].rstrip(b"\x00").decode("ascii", "replace")
        if name.startswith("stxt"):
            guards.append(name)
    if guards:
        notes.append("copy protection present: %s" % ", ".join(guards))
    else:
        notes.append("no copy-protection sections in this build")

    pad = data[0x0F00:0x0FA8]
    bypassed = any(b != 0 for b in pad)
    if bypassed:
        notes.append("a loader patch is installed (the header padding holds "
                     "code), so the protection is already bypassed")
    elif guards:
        notes.append("the header padding is empty, so the protection looks "
                     "untouched")

    return (bool(guards) and not bypassed), notes


def write_patiently(path, data, tries=6, pause=0.4):
    """
    Write a file, allowing for Windows holding it open for a moment.

    A freshly written executable gets scanned, and during that scan it
    cannot be opened for writing again. Waiting and retrying turns a hard
    failure into a short delay. Returns False if it never became writable,
    so the caller can say so instead of leaving half a patch behind.
    """
    for attempt in range(tries):
        try:
            with io.open(path, "wb") as f:
                f.write(data)
            return True
        except (PermissionError, OSError):
            if attempt == tries - 1:
                return False
            time.sleep(pause)
    return False


def wide(ch):
    """The game's own full-width code for an ASCII character."""
    if not (0x20 <= ord(ch) <= 0x7E):
        raise ValueError("not ASCII: %r" % ch)
    return None  # filled in from the file, see wide_table


LEAD = 0x20          # see cell_bytes


def cell_bytes(ch):
    """
    The two bytes to put in a keyboard cell so that pressing it types `ch`.

    The obvious answer was the game's own full-width code -- Ａ is 0x8260,
    and the game writes full-width Latin into its own save files, so it can
    clearly render it. That was tried and it does not work: pressing Ａ puts
    a single byte 0x60 in the name field, pressing ｂ puts 0x82, and so on.
    Measured twice, on two different layouts, and both times what appeared
    was exactly the SECOND byte of each code with the first one gone.

    Why the first byte is lost is not established -- the kana use the same
    0x82 first byte and they work -- so rather than guess at the cause a
    third time, this works with the behaviour as measured: put the letter
    itself in the second byte, where whatever survives is the letter.

    The first byte is a space. If it turns out to be dropped, the name is
    plain ASCII and reads correctly; if it is kept after all, the name gains
    a space before each letter, which is wrong but still legible -- rather
    than a row of symbols. A space is also safely clear of the 0x81 0x40
    pair the game reads as an empty cell.
    """
    return bytes([LEAD, ord(ch)])


def find_block(data, top_row_text, patched_top=None):
    """
    Where a keyboard page lives, found by its own contents.

    Returns the offset of the block's FIRST row in the file, which is the
    BOTTOM row on screen.

    Looks for the page as it was patched as well as as it shipped, so the
    tool can still report on a game it has already changed. Searching only
    for the kana meant that once the letters were in, --show declared the
    table missing.

    Requiring the pattern to appear only once was too strict: the run of
    full-width letters a patched page starts with turns up a second time
    elsewhere in the executable, and the search gave up. What identifies a
    keyboard row is its shape, not its rarity -- it ends in two zero bytes
    thirty bytes in, with five more rows above it at the same stride.
    """
    end_of_row = bytes([0, 0])
    for needle_text in (top_row_text, patched_top):
        if not needle_text:
            continue
        needle = needle_text.encode("cp932")
        at = data.find(needle)
        while at >= 0:
            for lead in (0, 2, 4, 6):        # the row may be centred
                row = at - lead
                if row >= 0 and data[row + 30:row + 32] == end_of_row:
                    first = row - (ROWS - 1) * ROW_STRIDE
                    if first >= 0:
                        return first
            at = data.find(needle, at + 1)
    return None


def build_page(layout, wmap=None):
    """The six rows of a page, bottom row first, as the file stores them."""
    rows = []
    for screen_row in range(ROWS - 1, -1, -1):
        text = layout.get(screen_row, "")
        # Start at the first cell, exactly as the kana did.
        #
        # Centring the letters looked tidier and was wrong. Measured against
        # the shipped picture: the first kana sits at x=68, which is cell 0,
        # while centring put the first letter at x=104, which is cell 1 --
        # so every letter sat one cell to the right of the grid the game
        # counts in, and pressing a key gave the character beside it.
        pad = 0
        cells = []
        for i in range(CELLS):
            j = i - pad
            if 0 <= j < len(text):
                cells.append(cell_bytes(text[j]))
            else:
                cells.append(DEAD)
        rows.append(b"".join(cells) + b"\x00\x00")
    return b"".join(rows)


def printable(ch):
    """
    One character the console can certainly show.

    This has to run on a stranger's machine, where the console is often a
    code page that cannot represent kana at all -- printing them raw throws
    UnicodeEncodeError and the tool dies after having already written to the
    executable, which is the worst possible moment to fall over. Full-width
    Latin folds back to plain ASCII; anything else becomes a dot.
    """
    o = ord(ch)
    if 0xFF01 <= o <= 0xFF5E:
        return chr(o - 0xFEE0)
    if 0x20 <= o <= 0x7E:
        return ch
    if o == 0x3000:
        return "."
    # a character this console cannot show -- but "not shown" must not look
    # the same as "empty cell", or an untouched Japanese table reads as a
    # blank one
    return "#"


def decode_block(data, at):
    out = []
    for r in range(ROWS):
        o = at + r * ROW_STRIDE
        cells = []
        for c in range(CELLS):
            b = data[o + c * 2:o + c * 2 + 2]
            if b == DEAD:
                cells.append(".")
            elif b[0] == LEAD and 0x20 <= b[1] <= 0x7E:
                # our own cells: the letter lives in the second byte,
                # which is the byte the game keeps
                cells.append(chr(b[1]))
            else:
                try:
                    cells.append(printable(b.decode("cp932")))
                except Exception:
                    cells.append("?")
        out.append(cells)
    out.reverse()          # print top row first, as it appears on screen
    return out


def show(data, hira, kata):
    for label, at in (("page 1 (was hiragana)", hira),
                      ("page 2 (was katakana)", kata)):
        print("   %s, at 0x%06X:" % (label, at))
        for i, row in enumerate(decode_block(data, at)):
            print("      row %d  %s" % (i, " ".join(row)))


def keyboard_is_installed(game):
    """Does the character table in this copy already hold Latin letters?

    Asked by the interface patcher, so the keys can be painted to match
    what the table actually says rather than what this particular command
    was asked to do. Someone who adds the keyboard and later re-runs the
    ordinary install would otherwise get kana drawn on keys that type
    letters -- the same mismatch the split exists to prevent, reversed.

    Measured by comparing the table's bytes against the backup we made
    before changing them. Only that region is compared, so a no-CD patch
    somewhere else in the file does not affect the answer. No backup means
    we never changed the table, so the answer is no.
    """
    exe = os.path.join(game, EXE)
    backup = os.path.join(game, BACKUP)
    if not (os.path.exists(exe) and os.path.exists(backup)):
        return False
    try:
        with io.open(exe, "rb") as f:
            live = f.read()
        with io.open(backup, "rb") as f:
            orig = bytearray(f.read())
        span = ROWS * ROW_STRIDE
        for top in (HIRA_TOP, KATA_TOP):
            at = find_block(orig, top)
            if at is None:
                continue
            if live[at:at + span] != bytes(orig[at:at + span]):
                return True
    except Exception:
        # A check that cannot run must not invent an answer; saying "no"
        # leaves the keys in Japanese, which is the harmless way to be wrong.
        return False
    return False


def main(argv):
    game = None
    mode = "patch"
    i = 0
    while i < len(argv):
        if argv[i] == "--game" and i + 1 < len(argv):
            game = argv[i + 1]
            i += 1
        elif argv[i] == "--undo":
            mode = "undo"
        elif argv[i] == "--show":
            mode = "show"
        i += 1
    if not game:
        game = find_game(EXE)
        if not game:
            print("Princess Maker 4 -- Latin name-entry keyboard")
            print("   I could not find %s next to me or one folder up." % EXE)
            print("   Tell me where it is:  --game \"C:\\path\\to\\the game\"")
            return 1

    exe = os.path.join(game, EXE)
    backup = os.path.join(game, BACKUP)
    print("Princess Maker 4 -- Latin name-entry keyboard")
    print("   game: %s" % game)
    if not os.path.exists(exe):
        print("   %s not found here" % EXE)
        return 1

    if mode == "undo":
        if not os.path.exists(backup):
            # Not a failure. The keyboard is opt-in, so the ordinary
            # install never writes a backup, and an ordinary undo then
            # arrives here. Returning 1 made every normal undo print
            # "FAILED: the keyboard" at the end of a run in which
            # nothing had gone wrong. 2 means "there was nothing to do".
            print("   the keyboard was never added here, so there is")
            print("   nothing to put back. Leaving %s alone." % EXE)
            return 2
        with io.open(backup, "rb") as f:
            data = f.read()
        if not write_patiently(exe, data):
            print("   could not write %s -- close the game and try again." % EXE)
            return 1
        print("   original executable restored from %s" % BACKUP)
        return 0

    # If this was patched here before, start again from the original --
    # but in memory, not by writing the file twice.
    #
    # Starting again matters because the search looks for the kana it is
    # replacing, and after one pass they are gone; a second run would
    # otherwise fail, or worse, build on the first one's work.
    #
    # Doing it in memory matters because writing an executable and
    # immediately reopening it for writing is exactly what makes Windows
    # refuse: something scans a freshly written .exe and holds it for a
    # moment, and the second open came back "Permission denied". That only
    # showed up when the installer was run twice, which is the one case a
    # person is most likely to try.
    with io.open(exe, "rb") as f:
        data = bytearray(f.read())
    if os.path.exists(backup):
        print("   this was patched before; starting from the original")
        with io.open(backup, "rb") as f:
            data = bytearray(f.read())
    # the top row each page gets after patching, so an already-patched
    # game can still be inspected and undone
    protected, notes = inspect_protection(bytes(data))
    for n in notes:
        print("   %s" % n)
    if protected and "--force" not in argv:
        print()
        print("   NOT changing the executable.")
        print()
        print("   This copy still has its copy protection active, and that")
        print("   protection checks the file against itself before the game")
        print("   starts. Editing 384 bytes of it is enough to make the check")
        print("   fail, and then the game does not start at all.")
        print()
        print("   Everything else -- the whole script and the whole")
        print("   interface -- is unaffected and installs normally. Only the")
        print("   Latin keyboard needs this file.")
        print()
        print("   If your copy already has a no-CD patch and you want to try")
        print("   anyway, add --force. Undo puts the file back either way.")
        return 1

    p1_top = "".join(chr(ord(c) + 0xFEE0) for c in PAGE1[0])
    p2_top = "".join(chr(ord(c) + 0xFEE0) for c in PAGE2[0])
    hira = find_block(data, HIRA_TOP, p1_top)
    kata = find_block(data, KATA_TOP, p2_top)
    if hira is None or kata is None:
        print("   could not find the keyboard tables in this executable.")
        print("   It may be a different build. Nothing was changed.")
        return 1
    print("   page 1 table at 0x%06X, page 2 table at 0x%06X" % (hira, kata))

    if mode == "show":
        show(data, hira, kata)
        return 0

    new1 = build_page(PAGE1)
    new2 = build_page(PAGE2)
    want = ROWS * ROW_STRIDE
    if len(new1) != want or len(new2) != want:
        print("   built %d and %d bytes, expected %d each -- refusing"
              % (len(new1), len(new2), want))
        return 1

    if not os.path.exists(backup):
        with io.open(backup, "wb") as f:
            f.write(bytes(data))
        print("   original kept as %s" % BACKUP)

    data[hira:hira + want] = new1
    data[kata:kata + want] = new2
    if not write_patiently(exe, bytes(data)):
        print("   could not write %s -- something is holding it open." % EXE)
        print("   Close the game, and any virus scanner window, and try again.")
        print("   Nothing was changed.")
        return 1
    print("   %d bytes written" % (2 * want))
    print()
    print("   the keyboard now reads:")
    show(data, hira, kata)
    print()
    print("   Six characters per name is still the limit; that check is in")
    print("   the encrypted part of the file and cannot be edited here.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
