# The fixture read the real chats

*2026-11-23*

Someone was rendering a picture of a notebook that was not theirs. The notebook lived in a temporary directory, filled with invented people, so a page could be screenshotted without opening the real one. The script ran on the same machine as the real notebook, which is an ordinary thing to do. Pytest gives every test a fresh home directory. A script does not.

The page came back with 1,500 activity rows. They were not the fixture's. They were the last lines of the owner's real WeChat conversations, copied into the temp notebook by the first page build.

The path in is small. Capturing WeChat's keys writes `~/.co/wechat/keys.json`. That file means "this Mac can read WeChat," and the owner's notebook treats it as consent: reading your own chats locally is reversible, so the notebook turns the source on instead of asking. The page build, after an upgrade, backfills any local source the notebook has already consented to, so the People page is not a row of dashes until the next night. Both decisions are right for the notebook at `~/.co/rem`.

They are not a property of the home directory. The keys sit beside every notebook the process can see. The fixture had never stored a WeChat subscription. It inherited one, because the code asked the Mac and not the notebook. Then the backfill did what it was written to do, and the previews landed in a directory that was about to be thrown away. Nothing left the machine. The rows were deleted. The surprise remained: any second notebook, any ad-hoc render, was one page build away from the same copy.

A consent has to name whose it is. The default notebook, `~/.co/rem`, is the owner's, and a root can be marked as theirs with an `.state/owner-notebook` file. For that notebook, keys still mean on, including one that stored "not consented" before the migration. Everywhere else, WeChat stays off unless that notebook's own subscriptions file says it was consented. The page-build backfill asks those subscriptions, so it no longer borrows the Mac's keys. The night's onboarding goes one step further: a dictionary passed in from somewhere else is not consent unless the file lists it. The fixture renders. It does not read the real chats.
