---
description: The first co browser --engine wtf go_to on a machine with no artifact cached died at 120s and blamed the page. The 120s was the one-time browser download. The page was never asked.
tags: [Browser, WTF, CLI]
---

# The download was not the page

On a Linux machine with an empty WTF cache, the first command was:

```
co browser --engine wtf --headless go_to https://example.com
```

Two minutes later it said `go_to did not finish within 120s — it was waiting on the page to load.` The same command, run again, opened example.com in 16.5 seconds. Nothing about the page had changed. The first two minutes had gone into fetching `chrome/154.0.8037.58/linux-x86_64.tar.zst`, the browser the paid engine will not start without. The second run found that archive already on disk.

The 120 second clock is real, and it should stay real. It is what stops a command that is stuck on a page, or on a Keychain prompt, from holding its tab forever. The mistake was where the clock started. The first launch calls Onionwright's `prepare` before any navigation: manifest, compatibility, the download, the checksum, the extract. All of that sat inside the same deadline as the page. The terminal said nothing while it happened. The system engine, faced with the same kind of first run, at least says `one-time download` before it installs a browser. This path waited in silence and then named the wrong thing.

## What the clock is for

The download is once per machine. The page load is every time. Charging the first against the second means a slow link fails a command that would have worked, and the sentence you get back sends you to look at the network of the page rather than the archive that is still arriving.

Now, when the artifact is not already cached, the command says so on stderr, in the same voice as that system-engine line, and includes the size. If the installed Onionwright can report progress, those updates are printed too. The 120 seconds start counting when that download is finished. A timeout that still fires while the download is the thing in progress says it was waiting on the artifact, not on the page. A `go_to` whose browser is already up still dies at 120 seconds, and still says the page.

The second run was never the bug. It was the measurement that showed where the first 120 seconds had gone.
