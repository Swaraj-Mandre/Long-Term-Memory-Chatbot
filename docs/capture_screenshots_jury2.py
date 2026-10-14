"""
Takes the screenshots used in the Jury 2 presentation.

Same idea as capture_screenshots.py: the figures are taken from the running
application, so the slides always show what the system really does.

Start the server first, then run:

    .venv\\Scripts\\python.exe docs\\capture_screenshots_jury2.py http://127.0.0.1:8000

WARNING: it wipes the memory of the server it talks to, so point it at a test
copy, not at memory you want to keep.
"""

import os
import sys
import time

from playwright.sync_api import sync_playwright

SERVER = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "jury2")


def send_message(page, text):
    """Type one message, send it, and wait until the reply is finished."""
    done_before = page.locator(".msg-bot .msg-tag.shown").count()
    page.fill("#messageInput", text)
    page.click("#btnSend")

    # The tag under the bot's reply only appears once the turn is complete.
    for _ in range(180):
        time.sleep(0.5)
        if page.locator(".msg-bot .msg-tag.shown").count() > done_before:
            time.sleep(1.2)             # let the panel animations settle
            return
    raise TimeoutError("No reply arrived for: " + text)


def save(page, name, selector=None):
    """Save the whole page, or one part of it."""
    path = os.path.join(OUTPUT_DIR, name)
    if selector:
        page.locator(selector).last.screenshot(path=path)
    else:
        page.screenshot(path=path)
    print("  saved", name)


def save_chat(page, name, count):
    """
    Save only the last few chat items, in a narrow window.

    Below 1024 px the side panel hides and the chat fills the window, so the
    text comes out larger and stays readable on a slide.
    """
    page.set_viewport_size({"width": 900, "height": 1400})
    time.sleep(0.8)

    items = page.locator(".msg, .notice")
    boxes = [items.nth(i).bounding_box() for i in range(items.count())][-count:]
    top = min(b["y"] for b in boxes) - 8
    bottom = max(b["y"] + b["height"] for b in boxes) + 16
    page.screenshot(
        path=os.path.join(OUTPUT_DIR, name),
        clip={"x": 0, "y": top, "width": 900, "height": bottom - top},
    )
    print("  saved", name)

    page.set_viewport_size({"width": 1440, "height": 860})
    time.sleep(0.5)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(
            viewport={"width": 1440, "height": 860},
            device_scale_factor=2,      # sharp text when projected
        )

        # Start from an empty memory so the figures are reproducible.
        page.request.post(SERVER + "/api/reset", data="{}")
        page.goto(SERVER)
        page.wait_for_selector("#messageInput")
        time.sleep(1)
        save(page, "00_welcome.png")

        print("Session 1: good news, then a sarcastic bad day")
        send_message(page, "I got selected for the Google internship!!")
        send_message(page, "Great, another rejection email from Amazon. Just what I needed.")
        save(page, "01_full_interface.png")
        save(page, "01a_emotion_disagree.png", "#stepEmotion")
        save(page, "01b_two_tones.png", "#transcript")

        send_message(page, "I failed my DBMS exam again too. Nothing I do ever works.")
        save(page, "02_concern.png")
        save(page, "02a_tone_concern.png", "#stepTone")
        save(page, "02b_reply_concern.png", ".msg-bot")
        save_chat(page, "chat_tones.png", 6)

        print("Session 2: the bot remembers")
        page.click("#btnNewSession")
        time.sleep(1)
        send_message(page, "hey, I'm back")
        save(page, "03_cross_session.png")
        save(page, "03a_follow_up.png", "#transcript")
        save(page, "03b_timeline.png", ".timeline-panel")
        save_chat(page, "chat_follow_up.png", 3)

        print("Crisis handling")
        send_message(page, "I don't want to live anymore")
        save(page, "04_crisis.png")
        save(page, "04a_safety_card.png", ".msg-bot")
        save(page, "04b_crisis_emotion.png", "#stepEmotion")
        save(page, "04c_crisis_tone.png", "#stepTone")
        save(page, "04d_timeline.png", ".timeline-panel")
        save_chat(page, "chat_crisis.png", 2)

        browser.close()

    print()
    print("All screenshots written to", OUTPUT_DIR)


if __name__ == "__main__":
    main()
