"""
Takes the screenshots used in the presentation.

Why this is a script rather than pressing Print Screen: the figures in the
slides have to match what the system actually does. Running this again after
any change regenerates every figure from the live application, so the slides
can never drift away from the real behaviour.

Before running it, start the server in another terminal:

    .venv\\Scripts\\python.exe run.py

Then run:

    .venv\\Scripts\\python.exe docs\\capture_screenshots.py
"""

import os
import time

from playwright.sync_api import sync_playwright

SERVER = "http://127.0.0.1:8000"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# The conversation used in the figures. Split into two sessions so the
# screenshots can show memory surviving from one session into the next.
SESSION_ONE = [
    "Hi, my name is Swaraj and I live in Pune. "
    "I study Artificial Intelligence at MIT ADT University.",
    "My favourite food is misal pav and I have a dog named Bruno.",
]

SESSION_TWO = [
    "Do you remember where I live?",
    "Actually I moved to Mumbai last week.",
    "So which city am I in now?",
]

PRIVACY_MESSAGE = "My email is swaraj.demo@example.com and my phone is 9876543210"


def send_message(page, text):
    """Type one message, send it, and wait for the reply to arrive."""
    replies_before = page.locator(".bubble-bot").count()

    page.fill("#messageInput", text)
    page.click("#btnSend")

    # The reply is written into a placeholder bubble that first says
    # "thinking...". We wait until a new bubble exists and no longer says that.
    for _ in range(120):
        time.sleep(0.5)
        bubbles = page.locator(".bubble-bot")
        if bubbles.count() > replies_before:
            last = bubbles.nth(bubbles.count() - 1).inner_text()
            if last.strip() and last.strip() != "thinking...":
                return last
    raise TimeoutError("No reply arrived for: " + text)


def save(page, name, selector=None):
    """Save a screenshot of the whole page, or of one part of it."""
    path = os.path.join(OUTPUT_DIR, name)
    if selector:
        page.locator(selector).screenshot(path=path)
    else:
        page.screenshot(path=path)
    print("  saved", name)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()

        # A slightly larger window than usual, and a higher pixel density, so
        # the text stays sharp when the image is projected.
        page = browser.new_page(
            viewport={"width": 1500, "height": 940},
            device_scale_factor=2,
        )

        # Start from an empty memory so the figures are reproducible.
        page.request.post(SERVER + "/api/reset", data="{}")
        page.goto(SERVER)
        page.wait_for_selector("#messageInput")

        print("Session 1: teaching the assistant some facts")
        for message in SESSION_ONE:
            send_message(page, message)

        # Figure: facts being extracted and scored on the first turn.
        save(page, "01_facts_extracted.png")
        save(page, "01a_retrieval_panel.png", "#retrievedList")

        print("Session 2: starting fresh and testing recall")
        page.click("#btnNewSession")
        time.sleep(1)

        send_message(page, SESSION_TWO[0])

        # Figure: the assistant answering from the database alone, after the
        # recent-message list was cleared.
        save(page, "02_cross_session_recall.png")

        print("Session 2: contradicting an earlier fact")
        for message in SESSION_TWO[1:]:
            send_message(page, message)

        # Figures: the full conversation, and close-ups of the two panels that
        # answer the likely jury questions.
        save(page, "03_full_interface.png")
        save(page, "03a_contradiction_panel.png", "#contradictionList")
        save(page, "03b_memory_store.png", "#memoryList")
        save(page, "03c_statistics.png", "#statGrid")

        print("Privacy: personal details removed before storing")
        send_message(page, PRIVACY_MESSAGE)
        time.sleep(1)
        save(page, "04_privacy.png")
        save(page, "04a_privacy_store.png", "#memoryList")

        print("Tech stack panel")
        page.click("#stackToggle")
        time.sleep(0.6)
        save(page, "05_tech_stack.png")

        browser.close()

    print()
    print("All screenshots written to", OUTPUT_DIR)


if __name__ == "__main__":
    main()
