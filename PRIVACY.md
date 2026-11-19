# Privacy Notice — AI Workmate

**Last updated: 19 November 2026**

AI Workmate is currently a locally run, early-stage project. This notice describes the current local version; it is not a promise about how a future hosted version will operate.

## Information the app handles

When you use AI Workmate, it may handle:

- Notes and text you enter for organisation.
- AI-generated summaries, action items, priorities, suggested next steps, and drafts.
- Tasks and task-completion status.
- Saved-session titles, notes, and generated results.
- Your theme preference.

## Where information is stored

- Saved sessions and the theme preference are stored in your browser's local storage on your device and browser profile.
- The app does not currently provide user accounts or a built-in cloud-sync service.
- Workspace backup exports create a JSON file on your device. That file can contain your saved sessions and their contents. Keep it somewhere private and do not share it publicly.
- Clearing browser site data or using a different browser profile/device may make locally saved sessions unavailable. Export a backup if you need a separate copy.

## AI processing by Google Gemini

When you choose to organise notes, the text you submit is sent from the local Python backend to the Google Gemini API to generate the result. The backend uses the `GEMINI_API_KEY` environment variable; the key is not meant to be placed in the frontend or committed to this repository.

Google processes API requests under its applicable terms and data policies. Review Google's current Gemini API terms and privacy information before submitting sensitive or confidential information. AI Workmate does not control Google's processing or retention practices.

## Network and hosting

The current Python server binds to `127.0.0.1` (localhost), meaning it is intended to run on the same computer. This repository is source code, not a hosted multi-user service. Do not expose the local server to the public internet or deploy it for other users without a separate security and privacy review.

## Your choices and precautions

- Do not enter passwords, payment-card details, government identifiers, confidential work information, or other sensitive data.
- Use your own Gemini API key and keep it secret.
- Protect exported JSON backups; they may contain the full text of your sessions.
- You can remove saved sessions from the app. You can also clear the browser's local storage for this app, but doing so may permanently delete sessions that have not been backed up.

## Contact and updates

This is an independently developed project. For questions or feedback, use the contact method provided by the project maintainer on the project's GitHub profile.

This notice should be reviewed and updated before any hosted release, account system, analytics, third-party integration, or other change to data handling.
