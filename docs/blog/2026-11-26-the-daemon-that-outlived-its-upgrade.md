# The daemon that outlived its upgrade

A Mac had the new co and the new onionwright on disk, and still could not open a page. Status said the browser was not open. Switching to system Chrome was refused, and the only command on offer was `co browser close`, which would have dropped four tabs other sessions had reserved. Both of the fixes for those errors were already installed. They had shipped the day after the browser daemon had started, and a running Python process does not go back and import them.

The process answering the socket was the one from the night before. It still spoke the old runtime error and the old engine pin, because those were the modules it had loaded at start. Nothing in `co browser status` said so. The versions on disk and the versions in the process were different facts, and the CLI only knew the first.

Status now names the co and onionwright that daemon imported, and the time it started, next to what this client has installed. When those differ and no browser is open, the CLI restarts the daemon itself. With no tab reserved, it just does that. With reservations it can replay, it carries them onto the new process, hold window included. When it cannot — a command still recorded, or a board it cannot read — it leaves the daemon alone and names the one command that would end them, and how many reservations that is.
