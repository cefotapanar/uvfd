# -*- coding: utf-8 -*-
"""
Version of UVFD.

New version: raise VERSION, write CHANGES (newest first), then
`python build.py --release`. Every running UVFD sees the new GitHub release
and offers the update.
"""

VERSION = "1.0.0"

#: GitHub repository the updater reads releases from (must be public).
REPO = "cefotapanar/uvfd"

#: Shown in the "New version" window of OLDER installations. Newest first;
#: earlier entries keep their version tag, so a jump over several versions
#: still shows everything.
CHANGES = {
    "mk": [
        "Прва верзија: мониторинг во живо, старт/стоп и Hz преку RS-485, подесувања по "
        "категории со пребарување, Read/Load на сите параметри, следење на BIOS верзии.",
    ],
    "en": [
        "First version: live monitoring, start/stop and Hz over RS-485, settings by "
        "category with search, Read/Load of all parameters, BIOS version tracking.",
    ],
}
