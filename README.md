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

## Quick start on Windows

1. Download the repository using **Code → Download ZIP**, then extract it.
2. Make sure all project files stay together in the extracted folder.
3. Install Python 3.8 or later if it is not already installed.
4. Double-click **Start_AI_Workmate.bat**.
5. When prompted, enter your Gemini API key. Input is hidden and the launcher does not save the key.
6. The browser should open to AI Workmate. Keep the launcher window open while using the app; press **Ctrl+C** in that window to stop it.

No third-party Python packages are required.

## Manual start (alternative)

If you prefer to start it manually:

1. Open Command Prompt in the project folder.
2. Set your Gemini API key for that Command Prompt window:
   ```bat
   set GEMINI_API_KEY=YOUR_GEMINI_API_KEY
   ```
3. Start the server:
   ```bat
   python app.py
   ```
4. Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

Keep the Command Prompt window open while using the app. Press **Ctrl+C** to stop the server.

## API key safety

- Get your own Gemini API key through Google AI Studio.
- The quick launcher prompts for the key without displaying typed input and does not save it to a file.
- Keep the key private; never paste it into the HTML file, screenshots, public posts, or GitHub.
- Do not commit any file containing your API key.

## Data and privacy notes

- Saved sessions are stored in the browser's local storage on that browser profile and device.
- Clearing browser site data can remove saved sessions. Export a JSON backup regularly.
- The local server binds to `127.0.0.1`, so this setup is intended for use on the same computer, not as a public hosted service.
- Notes submitted for AI organisation are sent to Google's Gemini API. Do not submit confidential or sensitive information.

## Project status

AI Workmate is an early-stage personal project being prepared for first-user feedback. This repository is a source-code showcase and local-run setup; it is not a hosted multi-user service.

## Privacy

Read the [AI Workmate Privacy Notice](PRIVACY.md) to understand local storage, Gemini API processing, and backup-file handling.

## Feedback

If you try AI Workmate, feedback on usability, reliability, and the note-to-action workflow is welcome.
