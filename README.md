# AI Workmate

AI Workmate is a personal AI workspace assistant that turns notes into an organised workspace. Add notes, let Gemini structure them, then manage the resulting tasks and saved sessions.

## What it does

- Organises notes into a summary, action items, priorities, suggested next steps, and useful drafts.
- Lets you mark tasks complete and track progress.
- Supports task management and saved-session history.
- Lets you search, sort, and rename saved sessions.
- Supports workspace backup and restore using JSON.
- Includes dark and light themes.

## How it works

- **Frontend:** HTML, CSS, and JavaScript.
- **Backend:** Python's built-in HTTP server.
- **AI:** Google Gemini API.
- **Storage:** Saved sessions and preferences are stored in the browser's local storage. Export a workspace backup to keep a separate copy.

## Run locally on Windows

1. Download the repository using **Code → Download ZIP**, then extract it.
2. Make sure `index.html` and `app.py` are in the same folder.
3. Install Python 3.8 or later if it is not already installed.
4. Open Command Prompt in that folder.
5. Set your Gemini API key for that Command Prompt window:

   ```bat
   set GEMINI_API_KEY=YOUR_GEMINI_API_KEY
   ```

6. Start the server:

   ```bat
   python app.py
   ```

7. Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

Keep the Command Prompt window open while using the app. Press `Ctrl+C` in that window to stop the server.

## API key safety

- Get your own Gemini API key through Google AI Studio.
- Keep the key in the `GEMINI_API_KEY` environment variable.
- Never paste your API key into the HTML file, screenshots, public posts, or GitHub.
- Do not commit a file containing your API key.

## Data and privacy notes

- Saved sessions are stored in the browser's local storage on that browser profile and device.
- Clearing browser site data can remove locally saved sessions. Export a JSON backup regularly.
- The local server binds to `127.0.0.1`, so this setup is intended for use on the same computer, not as a public hosted service.

## Project status

AI Workmate is an actively developed project. The local workflow and core features are being tested and refined ahead of a wider public release. This repository is currently a source-code showcase and local-run setup; it is not a hosted multi-user service.

## Feedback

If you try AI Workmate, feedback on usability, reliability, and the note-to-action workflow is welcome.