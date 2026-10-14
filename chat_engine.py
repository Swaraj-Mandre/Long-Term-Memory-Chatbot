"""
Runs one turn of conversation, start to finish.

What happens each time the user sends a message:

  1. Read the message: pull out lasting facts, and work out how the user feels
     (local emotion model + LLM, see sentiment.py).
  2. Safety check. In a crisis we stop here and give a fixed safe reply.
  3. Save the facts, replacing older versions if they contradict.
  4. Search memory for whatever is relevant to this message.
  5. Put the memories, the emotion and the chosen tone into the prompt, and ask
     the model for a reply.
  6. Save the message itself, and trim the store if it has grown too large.

Steps 3 and 4 together are retrieval-augmented generation. The usual version of
RAG searches a set of documents; here the thing being searched is the user's own
history.
"""

import config
import debug_log
import safety
import sentiment
from llm_client import LLMClient, LLMError
from memory_manager import MemoryManager
from mood_log import MoodLog
from tone import choose_tone


# ---------------------------------------------------------------------------
# The instructions we give the model when reading each message
# ---------------------------------------------------------------------------
# One call does two jobs: it pulls out facts AND reads the user's emotion.
# This model reasons for a few seconds before every answer, so a separate
# call for emotion would make every reply noticeably slower.
#
# Details in here that matter a lot:
#
#   - We insist on a fixed list of key names. If the model writes "city" one
#     time and "location" the next, the system will never realise the two are
#     about the same thing, and contradictions will go undetected.
#
#   - The emotion must be one of the same 7 labels the local model uses, so
#     the two readers can be compared directly.
#
#   - We ask for JSON only. Anything else is harder to parse reliably.

READ_MESSAGE_PROMPT = """You read a user's message. You pull out lasting facts about them, and you notice how they feel.

Reply with ONLY a JSON object in this shape:
{"facts": [{"key": "...", "value": "..."}],
 "emotion": "...",
 "reason": "...",
 "risk": "..."}

emotion: exactly one of joy, sadness, anger, fear, surprise, disgust, neutral.
  Read the whole situation, not single words. "Great, I failed again" is sadness, not joy.
reason: a few words on why they feel that way, e.g. "worried about exam results". Empty if neutral.
risk: "crisis" if they hint at self-harm or not wanting to live,
      "concern" if they seem to be really struggling,
      otherwise "none".

Rules for facts:
1. Use one of these key names whenever it fits:
   name, age, city, country, job, employer, college, course, year_of_study,
   hobby, favourite_food, favourite_sport, favourite_colour, language,
   dietary_preference, pet, goal, project, birthday
   Only invent a new key (lowercase, underscores) if none of these fit.
2. Only record facts about THE USER that stay true over time.
3. Ignore questions, greetings, and passing comments.
4. If the message contains no lasting fact, use "facts": []

Examples:
Message: "Hi, I'm Swaraj and I live in Pune"
Reply: {"facts": [{"key": "name", "value": "Swaraj"}, {"key": "city", "value": "Pune"}], "emotion": "neutral", "reason": "", "risk": "none"}

Message: "I moved to Mumbai last month for a new job at Infosys and I love it"
Reply: {"facts": [{"key": "city", "value": "Mumbai"}, {"key": "employer", "value": "Infosys"}], "emotion": "joy", "reason": "happy with new job", "risk": "none"}

Message: "What did I tell you about my college?"
Reply: {"facts": [], "emotion": "neutral", "reason": "", "risk": "none"}

Message: "I failed my exam again, nothing I do ever works"
Reply: {"facts": [], "emotion": "sadness", "reason": "failed exam again", "risk": "concern"}
"""


def remove_em_dashes(text):
    """
    Replace em dashes with commas.

    The prompt already asks the model not to use them, but a reasoning model
    does not always follow style rules, so we make sure here. It changes
    punctuation only, never words.
    """
    return text.replace(" — ", ", ").replace("—", ", ")


class ChatEngine:
    def __init__(self, session_id="session-1", memory=None, llm=None):
        self.session_id = session_id
        self.memory = memory or MemoryManager()
        self.llm = llm or LLMClient()

        # Jury 2: the local emotion model, and the record of past moods.
        self.emotion_model = sentiment.EmotionClassifier()
        self.moods = MoodLog()

        # Working memory: the last few messages, kept exactly as written.
        # This is a plain list in memory, so it is emptied when a new session
        # starts. That is deliberate - it is how we prove that anything the bot
        # still remembers afterwards came from the database, not from here.
        self.working_memory = []

        # Details of the most recent turn, shown in the interface panel.
        self.last_turn = {}

        # Counts turns so the console output is easy to follow.
        self.turn_number = 0

    # -----------------------------------------------------------------------
    # Step 1: read the message (facts + emotion)
    # -----------------------------------------------------------------------
    def read_message(self, message):
        """
        Ask the model for the facts in this message and how the user feels.

        Returns {"facts": [...], "emotion": ..., "reason": ..., "risk": ...}.
        If the model cannot be reached, everything comes back empty rather than
        raising, so a network problem cannot stop the conversation. The local
        emotion model still works in that case.
        """
        empty = {"facts": [], "emotion": None, "reason": "", "risk": None}
        try:
            result = self.llm.chat_json([
                {"role": "system", "content": READ_MESSAGE_PROMPT},
                {"role": "user", "content": message},
            ])
        except LLMError:
            return empty

        if not isinstance(result, dict):
            return empty

        facts = []
        for item in result.get("facts") or []:
            if isinstance(item, dict) and item.get("key") and item.get("value"):
                facts.append({
                    "key": str(item["key"]),
                    "value": str(item["value"]),
                })

        return {
            "facts": facts,
            "emotion": result.get("emotion"),
            "reason": str(result.get("reason") or ""),
            "risk": str(result.get("risk") or "none").lower(),
        }

    # -----------------------------------------------------------------------
    # Step 5: build the prompt
    # -----------------------------------------------------------------------
    def build_messages(self, message, memories, mood=None, tone=None):
        """
        Assemble what we send to the model.

        The retrieved memories go into the system message rather than being
        pretended to be part of the conversation. That keeps a clean line
        between what the user actually said and what we looked up for them.

        The emotion and tone go in the same place. This is the whole of
        "adjust the reply tone": we do not post-edit the reply, we tell the
        model up front how to write it.
        """
        if memories:
            lines = []
            for memory in memories:
                label = "FACT" if memory["type"] == "semantic" else "EARLIER"
                lines.append("- [%s] %s" % (label, memory["text"]))
            memory_section = "\n".join(lines)
        else:
            memory_section = "- (nothing relevant found)"

        system_prompt = (
            "You are a helpful assistant that remembers this user between "
            "conversations.\n\n"
            "WHAT YOU REMEMBER ABOUT THEM:\n"
            + memory_section
            + "\n\n"
            "How to use this:\n"
            "- Refer to these naturally when they are relevant. Do not read the "
            "list back to the user.\n"
            "- Items marked FACT are current. Outdated versions have already "
            "been filtered out, so you can trust them.\n"
            "- If they ask something these notes do not cover, say you do not "
            "know rather than guessing.\n"
            "- Keep replies under 80 words.\n"
            "- Write in plain, simple sentences. Do not use em dashes."
        )

        if mood and tone:
            system_prompt += (
                "\n\nHOW THEY FEEL RIGHT NOW: %s (confidence %.2f)\n"
                "HOW TO REPLY: %s\n"
                "Never name the emotion back to them like a label "
                "(\"I detect sadness\"). Just let it shape how you write."
                % (mood["emotion"], mood["confidence"], tone["instruction"])
            )

        # How they felt in earlier sessions. This is what lets the bot ask
        # "how did the exam go?" a week later.
        earlier = self.moods.earlier_sessions(self.session_id)
        if earlier:
            lines = ["- %s: %s (%s)" % (e["time"][:10], e["emotion"], e["reason"])
                     for e in earlier]
            system_prompt += (
                "\n\nHOW THEY FELT IN EARLIER CONVERSATIONS:\n" + "\n".join(lines)
                + "\nIf it is relevant and kind to do so, you may follow up on these."
            )

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.working_memory[-config.WORKING_MEMORY_TURNS:])
        messages.append({"role": "user", "content": message})
        return messages

    # -----------------------------------------------------------------------
    # The whole turn
    # -----------------------------------------------------------------------
    # A turn is split into parts, because there are two ways to run it: all at
    # once (send) or streamed piece by piece (send_stream). Both use the same
    # before-and-after code, so the two paths cannot drift apart and start
    # behaving differently.
    #
    #   _before_reply -> steps 1 to 4   (read, safety, store facts, search)
    #   the reply     -> step 5         (this is the part that can stream)
    #   _after_reply  -> step 6         (save the message, trim, record)
    # -----------------------------------------------------------------------
    def _before_reply(self, message):
        """Steps 1 to 4. Returns everything steps 5 and 6 will need."""
        self.turn_number += 1
        debug_log.turn_header(self.turn_number, self.session_id, message)

        # 1: read the message. If it already contains a crisis phrase we skip
        # the LLM entirely: the safe reply must not depend on a network call.
        debug_log.step(1, "reading the message: facts and emotion")
        crisis_words = safety.find_crisis_words(message)
        if crisis_words:
            reading = {"facts": [], "emotion": None, "reason": "", "risk": None}
        else:
            reading = self.read_message(message)

        local = self.emotion_model.classify(message)
        mood = sentiment.combine(local, reading["emotion"])
        if crisis_words:
            mood["agreement"] = "llm skipped"
        debug_log.emotion(local, reading["emotion"], mood)

        # 2: safety check, using this message and the session's earlier moods.
        debug_log.step(2, "safety check and tone")
        history = self.moods.this_session(self.session_id) + [mood]
        safety_result = safety.decide_level(message, reading["risk"], history)
        tone = choose_tone(mood["emotion"], safety_result["level"])
        debug_log.safety(safety_result, tone)

        # Remember the mood. In a crisis we keep only a neutral note, not the
        # LLM's description of what was said.
        is_crisis = safety_result["level"] == safety.CRISIS
        reason = "distress flagged" if is_crisis else reading["reason"]
        self.moods.add(self.session_id, mood, reason, safety_result["level"])

        context = {
            "facts_found": [],
            "contradictions": [],
            "memories_used": [],
            "mood": mood,
            "tone": tone,
            "safety": safety_result,
            "helplines": safety.HELPLINES if is_crisis else [],
        }
        if is_crisis:
            debug_log.note("crisis: skipping memory and the LLM, using the fixed safe reply")
            return context

        # 3: store the facts, noting anything they replaced.
        if reading["facts"]:
            debug_log.step(3, "writing those facts to memory")
        else:
            debug_log.note("no lasting facts in this message, nothing written")

        for fact in reading["facts"]:
            new_record, replaced = self.memory.remember_fact(
                fact["key"], fact["value"], self.session_id
            )
            context["facts_found"].append({
                "id": new_record["id"],
                "key": new_record["metadata"]["key"],
                "value": new_record["metadata"]["value"],
            })
            if replaced is not None:
                context["contradictions"].append({
                    "key": replaced["metadata"]["key"],
                    "old_value": replaced["metadata"]["value"],
                    "new_value": new_record["metadata"]["value"],
                    "old_id": replaced["id"],
                    "new_id": new_record["id"],
                })

        # 4: search memory for anything relevant to this message.
        debug_log.step(4, "searching memory")
        context["memories_used"] = self.memory.recall(message)
        return context

    def _after_reply(self, message, reply, model_used, context):
        """Step 6, plus recording what happened for the interface panel."""
        # A crisis message is not stored word for word in long-term memory.
        # It stays in working memory only, so the next few replies still know
        # what was said and stay careful.
        pruned = []
        if context["safety"]["level"] != safety.CRISIS:
            self.memory.remember_message(message, self.session_id)
            pruned = self.memory.prune()

        self.working_memory.append({"role": "user", "content": message})
        self.working_memory.append({"role": "assistant", "content": reply})

        self.last_turn = dict(context)
        self.last_turn.update({
            "pruned_count": len(pruned),
            "model": model_used,
            "tokens_used": self.llm.total_tokens,
            "summary": self.memory.summary(),
        })

        debug_log.turn_footer(self.last_turn["summary"], len(pruned))
        return self.last_turn

    def _offline_reply(self, memories, error):
        """
        What to say when the model cannot be reached.

        We answer from memory alone rather than failing, so the memory side of
        the project can still be demonstrated without a working connection.
        """
        if memories:
            return (
                "I cannot reach the language model right now, but here is "
                "what I have stored:\n"
                + "\n".join("- " + memory["text"] for memory in memories)
            )
        return "I cannot reach the language model right now (%s)." % error

    def send(self, message):
        """
        Handle one user message and return (reply, details).

        `details` describes everything that happened internally, which is what
        the interface panel displays: the emotion, the tone chosen, the safety
        level, which memories were retrieved and any contradiction resolved.
        """
        context = self._before_reply(message)

        if context["safety"]["level"] == safety.CRISIS:
            reply, model_used = safety.CRISIS_REPLY, "fixed safe reply"
        else:
            # 5: ask the model, using the memories and the chosen tone.
            debug_log.step(5, "writing the reply")
            messages = self.build_messages(
                message, context["memories_used"], context["mood"], context["tone"]
            )
            try:
                reply = remove_em_dashes(self.llm.chat(messages))
                model_used = config.LLM_MODEL
            except LLMError as error:
                reply = self._offline_reply(context["memories_used"], error)
                model_used = "unavailable"

        details = self._after_reply(message, reply, model_used, context)
        return reply, details

    def send_stream(self, message):
        """
        The same turn, but handed back in pieces as it happens.

        Yields these events, in this order:

            {"type": "context", "details": ...}   emotion, tone, memories
            {"type": "thinking"}                  the model is reasoning
            {"type": "token", "text": ...}        a piece of the reply
            {"type": "done", "reply", "details"}  the finished turn

        Two reasons this is worth doing:

          - The "context" event goes out before the model has written a single
            word, so the panel shows the detected emotion, the chosen tone and
            the memories while the reply is still being written. In a demo
            that is the interesting part, and this way it appears first.

          - This model reasons before it answers, which takes around three
            seconds. Streaming lets us say honestly that it is thinking,
            instead of showing a spinner that looks like a frozen app.
        """
        context = self._before_reply(message)

        # Send the analysis out immediately. The reply follows after it.
        yield {"type": "context", "details": dict(context)}

        # Crisis: the fixed reply, sent in one piece. No model involved.
        if context["safety"]["level"] == safety.CRISIS:
            reply = safety.CRISIS_REPLY
            yield {"type": "token", "text": reply}
            details = self._after_reply(message, reply, "fixed safe reply", context)
            yield {"type": "done", "reply": reply, "details": details}
            return

        debug_log.step(5, "writing the reply, streamed")
        messages = self.build_messages(
            message, context["memories_used"], context["mood"], context["tone"]
        )

        pieces = []
        model_used = config.LLM_MODEL
        try:
            for piece in self.llm.chat_stream(messages):
                if piece["type"] == "thinking":
                    yield {"type": "thinking"}
                elif piece["type"] == "token":
                    text = remove_em_dashes(piece["text"])
                    pieces.append(text)
                    yield {"type": "token", "text": text}
            reply = "".join(pieces).strip()

        except LLMError as error:
            # The stream can fail after some text has already been shown on
            # screen. In that case we add the fallback to what is there rather
            # than replacing it, because the user has already read the start.
            model_used = "unavailable"
            fallback = self._offline_reply(context["memories_used"], error)
            shown = "".join(pieces).strip()
            if shown:
                yield {"type": "token", "text": "\n\n" + fallback}
                reply = shown + "\n\n" + fallback
            else:
                yield {"type": "token", "text": fallback}
                reply = fallback

        details = self._after_reply(message, reply, model_used, context)
        yield {"type": "done", "reply": reply, "details": details}

    def start_new_session(self, session_id):
        """
        Begin a fresh session.

        Clearing working_memory is the whole point: from here on, anything the
        bot recalls must have come out of the database. This is what
        demonstrates memory that lasts beyond a single conversation.
        """
        self.session_id = session_id
        self.working_memory = []
