# Twenty-four minutes with no co

On 22 November a Mac was upgrading to 1.9.7rc14. The command was the one the release notes have carried for a long time: `uv tool install --force`, with the output thrown away by the script that called it. `--force` does not upgrade in place. It removes the tool environment first, then tries to build the new one. The new one failed partway, and from 19:33 until about 19:57 there was no `co` on that machine.

A scheduled REM turn fired inside that window. launchd started the job, Python looked for the package, and the log got one line that is not a diagnosis: `No module named 'connectonion'`. The next turn, after someone installed by hand, ran fine. The turn that landed in the gap did not retry. It just died.

The same command is how a release gets onto the machines that cut the release. Any upgrade can open the same gap.

The installer now builds the new environment beside the one that is running, and it points `~/.local/bin/co` at the new one only after `co --version` succeeds and the new interpreter can import connectonion. If that check fails, the previous `co` is still the one on the path, and the reason is written down. `co doctor` and `co rem status` say the upgrade failed, or that it stopped halfway, instead of looking healthy while the clock is already broken.

The clock also stops assuming the package is there. The launchd and systemd jobs go through a small wrapper that lives with the notebook, not inside the tool environment. When the import fails it writes one line — co is upgrading or missing, this round is skipped, it will try again — waits a few minutes, and tries once more. There is no traceback. A turn that finds the package on the second look runs. A turn that still cannot find it leaves the log and exits, and the next tick is another chance rather than a crash.
