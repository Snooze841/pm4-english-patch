# -*- coding: utf-8 -*-
r"""
PM4 full translation + UI -- install everything, or take it all back off.

Princess Maker 4 keeps its English in three different places, so a full
translation has to touch three different things, and this runs all of them
in one go.

  the story      Every line of dialogue, every item name and description,
                 written into the file called 'script'. 16,544 story
                 lines, 89 item names and 89 item descriptions.

  the interface  The menus, the status window, the shop, the options, the
                 town map and the name-entry screens, which are not text at
                 all -- they are painted into pictures inside the 613 MB
                 archive called 'gd'. 507 pieces of lettering across
                 29 pictures, plus the 23 job cards.

  the keyboard   The name-entry screen offers kana and no way to type a
                 Latin name. The grid is driven by a small table of
                 character codes inside PrincessMaker4.exe; replacing it
                 with letters makes the keys type letters.

NOTHING OF THE GAME'S ARTWORK IS IN THIS PATCH

The interface part carries two things per label: where it is, and our own
lettering with an alpha channel. The background each label sits on is
rebuilt on your machine out of your own copy -- by shading between the
untouched pixels either side of a label, or by borrowing a piece of blank
parchment from elsewhere on the same picture. So the patch is small, and it
is a description of changes rather than a copy of somebody's art.

TAKING IT BACK OFF

Each part keeps its own way back, and --undo uses all three:
  script.orig_backup            your original script
  gd.ui_undo                    the pixels the interface patch replaced
  PrincessMaker4.exe.kbd_backup your original executable

Run:  python pm4_full_translate.py
      python pm4_full_translate.py --game "C:\Games\Princess Maker 4"
      python pm4_full_translate.py --undo
"""
import os
import sys
import traceback

# Where to look for the game, and where our own files are, are two
# different places once this is packed into a single .exe: PyInstaller
# unpacks the code into a temporary folder, so __file__ points there and
# not at the game. HERE therefore follows the executable, and BUNDLE the
# unpacked code.
if getattr(sys, "frozen", False):
    HERE = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE = getattr(sys, "_MEIPASS", HERE)
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
    BUNDLE = HERE
for _p in (BUNDLE, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

NAME = "PM4 full translation + UI"
KOFI = "https://ko-fi.com/jdksnoozer"


def line(ch="-", n=70):
    print(ch * n)


def find_game(given):
    """The folder holding the game, found the same way for every part."""
    if given:
        folder = os.path.abspath(given)
        if not os.path.isdir(folder):
            print("   there is no folder called %s" % folder)
            return None
        return folder
    for cand in (HERE, os.path.dirname(HERE)):
        if os.path.isfile(os.path.join(cand, "script")):
            return cand
    print("I could not find the game by myself.")
    print()
    print("Put this next to PrincessMaker4.exe and run it again, or type the")
    print("path to your Princess Maker 4 folder here.")
    print()
    try:
        answer = input("Princess Maker 4 folder: ").strip().strip('"').strip("'")
    except EOFError:
        answer = ""
    if not answer:
        return None
    return find_game(answer)


def have(game, filename):
    return os.path.isfile(os.path.join(game, filename))


def run_text(game, undo):
    try:
        import pm4_english_patch
    except Exception as e:
        print("   the story patcher is missing (%s)" % e)
        return False
    argv = ["--game", game] + (["--restore"] if undo else [])
    try:
        rc = pm4_english_patch.main(argv)
        if rc == 2:
            return None          # nothing to do, which is not a failure
        return rc in (0, None)
    except SystemExit as e:
        return e.code in (0, None)
    except Exception:
        traceback.print_exc()
        return False


def run_ui(game, undo, with_keyboard=False):
    try:
        import pm4_ui_apply
    except Exception as e:
        print("   the interface patcher is missing (%s)" % e)
        return False
    argv = ["--game", game] + (["--undo"] if undo else [])
    if with_keyboard and not undo:
        argv.append("--with-keyboard")
    try:
        rc = pm4_ui_apply.main(argv)
        if rc == 2:
            return None          # nothing to do, which is not a failure
        return rc == 0
    except Exception:
        traceback.print_exc()
        return False


def say_whether_keyboard_is_possible(game):
    """Look at the copy, instead of leaving the player to find out.

    The keyboard is left out of the ordinary install because on a copy whose
    copy protection is still live, editing the executable stops the game from
    starting. Whether that applies is something we can simply read off the
    file, so there is no reason to make someone try it and hope.
    """
    exe = os.path.join(game, "PrincessMaker4.exe")
    if not os.path.exists(exe):
        return
    try:
        import pm4_exe_keyboard
        with open(exe, "rb") as f:
            protected, notes = pm4_exe_keyboard.inspect_protection(f.read())
    except Exception:
        # A check that cannot run says nothing; it must not invent an answer.
        print("  I could not tell whether your copy can take it. Running")
        print("  \"Add the English keyboard.bat\" will look properly and")
        print("  refuse if it cannot.")
        return
    for n in notes:
        print("  %s" % n)
    if protected:
        print()
        print("  So the keyboard CANNOT be added to this copy as it stands.")
        print("  Everything else above is installed and works. A no-CD patch")
        print("  switches that check off, and then it can.")
    else:
        print()
        print("  So the keyboard CAN be added to this copy. To get it:")
        print("     run  \"Add the English keyboard.bat\"")
        print("  That paints the keys and changes the character table")
        print("  together, so what you see is what you type.")


def run_keyboard(game, undo):
    try:
        import pm4_exe_keyboard
    except Exception as e:
        print("   the keyboard patcher is missing (%s)" % e)
        return False
    argv = ["--game", game] + (["--undo"] if undo else [])
    try:
        rc = pm4_exe_keyboard.main(argv)
        if rc == 2:
            # 2 means there was nothing to do: the keyboard was never
            # added here, so an undo has nothing to put back. Reporting
            # that as a failure made every ordinary undo end in the word
            # FAILED, which is alarming and wrong.
            return None
        if rc not in (0, None):
            # Say what went wrong rather than only that something did. A
            # bare "FAILED" sent me hunting through three modules for a
            # fault that turned out to be a return code nobody printed.
            print("   the keyboard step returned %r" % (rc,))
        return rc in (0, None)
    except Exception:
        traceback.print_exc()
        return False


def main(argv):
    game = None
    undo = False
    # The keyboard is left out unless it is asked for.
    #
    # It is the only part that edits a program rather than data, and the
    # only part with a way to fail that a person cannot simply look at:
    # Princess Maker 4 ships behind SafeDisc, which checks the executable
    # against itself, so on a copy whose protection is still active the
    # edit stops the game starting. That happened to somebody. The story
    # and the interface touch nothing but the game's own data files and
    # are safe on any copy, so they are what "install" means.
    skip = {"keyboard"}
    want_keyboard = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--game" and i + 1 < len(argv):
            game = argv[i + 1]
            i += 1
        elif a == "--undo":
            undo = True
        elif a == "--no-ui":
            skip.add("ui")
        elif a == "--no-keyboard":
            skip.add("keyboard")
        elif a == "--keyboard":
            skip.discard("keyboard")
            want_keyboard = True
        elif a == "--no-story":
            skip.add("story")
        i += 1

    line("=")
    print("  %s" % NAME)
    line("=")
    print()

    game = find_game(game)
    if not game:
        print("Nothing was done.")
        return 1
    print("game folder    %s" % game)
    print("mode           %s" % ("putting it all back" if undo else "installing"))
    print()

    if undo:
        # taking it off, take all of it off -- someone who added the
        # keyboard separately should not have to remember that they did
        skip.discard("keyboard")

    doing_keyboard = "keyboard" not in skip

    parts = []
    if "story" not in skip:
        parts.append(("the story", run_text, "script"))
    if doing_keyboard:
        # Before the interface, not after. The interface step paints the
        # name-entry keys, and it may only do that if this step really
        # changed the character table underneath them.
        parts.append(("the keyboard", run_keyboard, "PrincessMaker4.exe"))
    if "ui" not in skip:
        parts.append(("the interface", run_ui, "gd"))
    if not doing_keyboard and not undo:
        print("  The Latin name-entry keyboard is NOT part of this install.")
        print("  It edits PrincessMaker4.exe, and on a copy whose protection")
        print("  is still active that stops the game starting.")
        print()
        say_whether_keyboard_is_possible(game)
        print()

    results = []
    keyboard_done = False
    for label, fn, needs in parts:
        line()
        print("  %s" % label)
        line()
        if not have(game, needs):
            print("   %s is not in this folder, so this part is skipped." % needs)
            results.append((label, None))
            print()
            continue
        if fn is run_ui:
            ok = fn(game, undo, keyboard_done)
        else:
            ok = fn(game, undo)
        if fn is run_keyboard:
            keyboard_done = bool(ok)
        results.append((label, ok))
        print()

    line("=")
    done = [l for l, ok in results if ok]
    failed = [l for l, ok in results if ok is False]
    skipped = [l for l, ok in results if ok is None]
    if done:
        print("  done:    %s" % ", ".join(done))
    if skipped:
        print("  skipped: %s" % ", ".join(skipped))
    if failed:
        print("  FAILED:  %s" % ", ".join(failed))
        print()
        print("  The parts that failed changed nothing. The parts that")
        print("  succeeded are installed and can be taken off with --undo.")
    line("=")

    if not undo and not failed:
        print()
        print("  Start the game and have a look. If anything is wrong, run")
        print("  this again with --undo and everything goes back.")
        print()
        print("  Made for free. If you want to say thanks: %s" % KOFI)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
