# nua-reels — Instagram trial reel robot

Posts the *Stay With Me* trial reels to Instagram (@nuua.mp3) through Instagram's own API, free, on GitHub Actions.

- `schedule.json` – what goes out when (Vienna time). Edit a `due` time to move a post.
  Since 29 Oct it only holds the 13 reels that are NOT scheduled in Metricool (Metricool has the other 27), in slots Metricool doesn't use, so nothing posts twice if a token is ever added.
- `posted.json` – what the robot already published (with links). It never posts the same id twice.
- `media` branch – the video files (served through jsDelivr).
- Runs every 10 minutes (GitHub can be 5–20 min late). Trial reels only go to non-followers; share the winners to your followers from the Instagram app.

**Pause everything:** Actions → instagram-trial-reels → `…` → Disable workflow.
**Post one reel right now:** Actions → instagram-trial-reels → Run workflow → enter the id (e.g. `N02`).
**Token check:** Run workflow with "Only check that the Instagram token works" ticked.
The Instagram token (`IG_TOKEN` secret) lasts 60 days.
