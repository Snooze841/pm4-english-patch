PRINCESS MAKER 4 IN ENGLISH
===========================

Princess Maker 4 (2005, Gainax / CyberFront) translated into English: the
story, the menus, the job cards, and a name-entry keyboard you can type on.

   Download:    PM4 full translation+UI.zip
   Executable:  PM4 full translation+UI.exe  -- the same binary, on its own,
                so you can hash or scan it without unpacking anything
   Sources:     translation/   -- the other thirteen files in that zip
   Checksums:   CHECKSUMS.txt  -- SHA-256 of all of it

To install: copy everything from the zip into your Princess Maker 4 folder
and run Install.bat. Undo.bat puts it all back. Nothing else is needed -- no
Python, nothing running alongside the game. HOW TO INSTALL.txt has the longer
version, including what to do if you use a no-CD patch.


BEFORE YOU INSTALL THIS, READ THIS BIT
--------------------------------------

A proper, human-made translation of Princess Maker 4 is in the works. I did
not know that when I started this. If you can wait, wait for theirs.

If anyone on that project finds anything here useful, take it. There is a
file called TRANSLATING IT YOURSELF.txt with the archive format, the cipher
the script is stored with, where every menu label lives and the font bug that
eats the first byte of every two byte character. That part took a long time
to work out and nobody should have to do it twice.

This is here in the meantime, for anyone who would rather play the game now
than later. Undo.bat puts everything back if you want to swap later.


THE EXECUTABLE IS THE RISKIEST FILE HERE
----------------------------------------

   PM4 full translation+UI.exe      6,405,815 bytes
   d7059c7d7c85532dfbed6b903c20f23e0eacb1076a56df6ea87fd3a09baafec6

It is the four Python files in translation/ packed with a Python interpreter
by PyInstaller, and nothing else. It is unsigned, and it can write 384 bytes
into another program -- that is the keyboard step.

SECURITY.txt lists every file the patcher can write, gives you a short script
that checks that claim against the code itself, and explains how to verify
your download against CHECKSUMS.txt and how to do all of this without running
my executable at all.

Three ways to avoid trusting it: upload that exact file to virustotal.com
(expect an engine or two to flag it; SECURITY.txt says why that result is
uninformative either way), or run the four .py files instead on Python 3.8 or
newer from python.org with no libraries to install, or build your own with
the exact PyInstaller command in SECURITY.txt -- which will not be
byte-identical to mine, because PyInstaller embeds paths and timestamps.


HOW THIS WAS MADE
-----------------

An AI assistant was used heavily throughout: working out the archive format
and the string cipher, writing the patcher, translating the script, and
checking the result. I am saying so plainly because you would rather know.
Nothing here asks you to trust me instead -- that is what the readable
sources, SECURITY.txt, CHECKSUMS.txt and Undo.bat are for. What was not
automated: the decisions. What to leave in Japanese, where a six-letter
English word had to fit four bytes, which banners were better left alone than
damaged. Those mistakes are mine. TRANSLATING IT YOURSELF.txt has the
technical half, including the cipher in room.g2 and the sprite definitions
that place every label.


WHAT IT TRANSLATES
------------------

   the story        all of it. 16,544 story lines, 89 item names and 89
                    item descriptions. No Japanese left in the script.

   the menus        26 pictures, 243 pieces of lettering: title menu, status,
                    shop, options, save and load, schedule, town map, name
                    entry, the seven award certificates, two intertitles.

   the job cards    all 23 schedule cards, every frame of each.

   the keyboard     3 more pictures and 264 more labels -- the keys
                    themselves -- plus 384 bytes in PrincessMaker4.exe that
                    decide what each key types. SEPARATE AND OPT-IN, see
                    below. All installed: 29 pictures, 507 labels.

Not touched: your saves, your settings, the music, the artwork.

The menu labels are painted into the game's own pictures inside gd, a 613 MB
archive, so shipping replaced pixels would mean shipping the artwork. Instead
this patch carries each label's position and our own lettering with a
transparency channel, and rebuilds the background from your own copy of the
game: 189 rectangles emptied, 47 shaded across from the pixels either side,
263 covered with parchment borrowed from blank keyboard cells, and the job
cards' shared plaque rebuilt from whatever a majority of your 23 cards agree
on. The last 8 need no erasing: the English is drawn straight over them.


IF YOU USE A NO-CD PATCH
------------------------

APPLY THE NO-CD PATCH FIRST, THEN ADD THE KEYBOARD.

Princess Maker 4 shipped behind copy protection that checks its own program
file at startup. While that check is live, nothing may edit
PrincessMaker4.exe -- including this patch's keyboard. Edit it anyway and the
game does not start. A no-CD patch switches that check off.

   1. install the game
   2. apply your no-CD patch
   3. Install.bat                      the story and the whole interface
   4. Add the English keyboard.bat

Step 4 inspects your copy first, and goes ahead when it prints

   copy protection present: stxt774, stxt371
   a loader patch is installed ... so the protection is already bypassed

and refuses, rather than stopping your game from starting, when it prints

   the header padding is empty, so the protection looks untouched
   NOT changing the executable.

A no-CD patch applied AFTER the keyboard replaces the program file and so
removes the keyboard: run "Add the English keyboard.bat" again. Undo.bat
restores PrincessMaker4.exe to exactly how it was when the keyboard was
added, no-CD patch and all; if you change your no-CD patch after adding the
keyboard and then undo, you get the older program file back, so reapply it.
The story and the interface never touch the program file.


WHAT IT KEEPS SO YOU CAN UNDO
-----------------------------

   script.orig_backup              your original story file
   gd.ui_undo                      the pixels the menu patch replaced
   PrincessMaker4.exe.kbd_backup   your original program file

Leave them alone -- Undo needs them. They never leave your machine. Each part
restores the original before patching again, so installing twice gives
exactly the same game as installing once.


KNOWN AND HONEST
----------------

- The keyboard is not installed by default, and that is deliberate. It is the
  only part that edits PrincessMaker4.exe instead of the game's data, and on
  a copy whose protection is still active that stops the game starting -- it
  happened to one tester. "Add the English keyboard.bat" inspects the file
  first and refuses when the protection looks live. So after an ordinary
  install the name-entry keys are still Japanese: a key's picture and the
  table saying what it types are two halves of one change, and installing
  only the first would give keys marked A that type a kana. Install.bat says
  which of the two cases you are in.

- Four pictures stay Japanese on purpose: the contest banners for the martial
  arts tournament, the dance contest, the art festival and the award
  ceremony. They are ornamented edge to edge, and no way of lifting the
  lettering off leaves the artwork clean. The certificates you win at those
  contests ARE translated, and so are the job cards and the schedule.

- The album's three section headings stay Japanese for the same reason, and
  so does decorative Japanese that is artwork rather than a label: the
  calligraphy scrolls in the Chinese-themed room, the katakana under the
  title logo.

- Six characters per name remains the limit on the name-entry screen. That
  count lives in a part of the program this patch does not reach, so "Alice"
  and "Sophie" fit and "Charlotte" does not.

- Dates and ages on the name-entry confirmation screen come out garbled. That
  is the game drawing two-byte text with a single-byte font, not something
  this patch introduced. The English dialogue is plain ASCII and is fine.

- Your virus scanner may object to the .exe. PyInstaller executables are a
  known false-positive magnet, it is unsigned, and it edits another program.
  None of that tells you whether it is safe; reading the source does, and
  SECURITY.txt has the longer version.


IF SOMETHING GOES WRONG
-----------------------

Run Undo.bat first -- the game is then exactly as it was before you started.
Then please report it here:

   https://github.com/Snooze841/pm4-english-patch/issues

Say which step you ran, what it printed, and whether you use a no-CD patch.
This is tested on one machine, so a report from a copy that is not mine is
the most useful thing anybody can send.


Made for free, for people who wanted to play this game and could not read it.
If you want to say thanks:  https://ko-fi.com/jdksnoozer
