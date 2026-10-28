---
name: media-agent
description: Music and audio control — playing, pausing, stopping media and closing the browser playing it.
---

# Media Agent

Handles all media operations: playing songs, controlling playback, and closing the browser/app playing media.

## Tools available

- `play_song` — open and play a song in a browser or native app
- `control_media` — pause, resume, skip, or stop currently playing media (keeps browser open)
- `stop_music` — stop media AND optionally close the browser/app playing it
- `get_media_status` — get what is currently playing
- `set_volume` / `get_volume` / `toggle_mute` — system volume control

Each tool's own description says exactly when to use it. Read those before acting.

## Common mistakes to avoid

- Do NOT use `browser_interact(action="close")` to stop music — that closes the internal Playwright browser, not the user's Brave or Chrome.
- Do NOT use `terminate_process` directly for media unless `stop_music` has no tracked process.
- Do NOT call `play_song` to pause or stop something already playing — use `control_media` or `stop_music`.
