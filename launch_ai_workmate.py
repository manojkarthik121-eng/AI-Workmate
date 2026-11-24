#!/usr/bin/env python3
"""Simple, secure local launcher for AI Workmate."""
import getpass
import os
import subprocess
import sys
import threading
import time
import webbrowser

URL = "http://127.0.0.1:8000"


def main():
    folder = os.path.dirname(os.path.abspath(__file__))
    app_path = os.path.join(folder, "app.py")
    page_path = os.path.join(folder, "index.html")

    if not os.path.isfile(app_path) or not os.path.isfile(page_path):
        print("AI Workmate files are missing. Keep this launcher in the project folder.")
        input("Press Enter to close...")
        return 1

    if sys.version_info < (3, 8):
        print("AI Workmate requires Python 3.8 or newer.")
        input("Press Enter to close...")
        return 1

    print("AI Workmate - local launcher")
    print("Your Gemini API key is entered privately and is not saved by this launcher.")
    try:
        key = getpass.getpass("Gemini API key (input hidden): ").strip()
    except Exception:
        print("Could not read the key securely in this terminal.")
        input("Press Enter to close...")
        return 1

    if not key:
        print("No API key entered. Nothing was started.")
        input("Press Enter to close...")
        return 1

    env = os.environ.copy()
    env["GEMINI_API_KEY"] = key
    try:
        process = subprocess.Popen([sys.executable, app_path], cwd=folder, env=env)
    except OSError as exc:
        print("Could not start AI Workmate:", exc)
        input("Press Enter to close...")
        return 1

    # Drop the launcher's copy of the key as soon as the child process is started.
    key = None
    env.pop("GEMINI_API_KEY", None)

    print("Starting AI Workmate. Keep this window open while using it.")
    print("Your browser will open shortly. Press Ctrl+C here to stop the server.")
    threading.Thread(
        target=lambda: (time.sleep(2), webbrowser.open(URL)),
        daemon=True
    ).start()

    try:
        return process.wait()
    except KeyboardInterrupt:
        print("\nStopping AI Workmate...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        return 0


if __name__ == "__main__":
    sys.exit(main())
