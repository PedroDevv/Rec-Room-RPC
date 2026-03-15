# Rec Room Discord RPC

Shows what you're doing in Rec Room as a Discord Rich Presence status. Room image, your profile picture, buttons to view the room and your profile, platform detection, the whole thing.

## What it shows

- The room you're in with its thumbnail
- Whether the game is in progress, the server is full, or you're just playing some fun rooms!
- Your profile picture as the small icon
- Dorm rooms and private rooms are handled without exposing anything
- Your platform (Quest, PC, Switch etc)
- A timer for how long you've been in the current room
- Buttons to view the room or your profile on rec.net

## Setup

Just run `RUNME.bat`. It'll check that Python is installed, grab all the dependencies, and launch the app. On first run a browser window opens for you to log into Rec Room — your password never gets stored or sent anywhere, only a session token is saved locally.

If you don't have Python, grab it at [python.org](https://www.python.org/downloads/). Make sure to check **Add Python to PATH** during install.

After setup the app runs in the background and waits for Rec Room to launch. When it detects Rec Room it activates automatically, and clears your status when you close the game.

Right-click the tray icon to manage settings or quit.

## Files

- `main.py` — the app
- `RUNME.bat` — installs dependencies and launches everything
- `config.json` — created automatically, stores your session. Delete it to log out.

## Notes

- If your session expires after a few months, a popup will appear asking you to log in again.
- To enable or disable running at Windows startup, right-click the tray icon.
- This project does NOT store your Rec Room session or send your token ANYWHERE. Your login data remains on device.
