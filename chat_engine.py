"""
Runs one turn of conversation, start to finish.

What happens each time the user sends a message:

  1. Read the message and pull out any lasting facts about the user.
  2. Save those facts, replacing older versions if they contradict.
  3. Search memory for whatever is relevant to this message.
  4. Put those memories into the prompt and ask the model for a reply.
  5. Save the message itself, and trim the store if it has grown too large.

Steps 3 and 4 together are retrieval-augmented generation. The usual version of
RAG searches a set of documents; here the thing being searched is the user's own
history.
"""

import config
from llm_client import LLMClient, LLMError
from memory_manager import MemoryManager


# ---------------------------------------------------------------------------
# The instructions we give the model when asking it to find facts
# ---------------------------------------------------------------------------
# Two details in here matter a lot:
#
#   - We insist on a fixed list of key names. If the model writes "city" one
#     time and "location" the next, the system will never realise the two are
#     about the same thing, and contradictions will go undetected.
#
#   - We ask for JSON only. Anything else is harder to parse reliably.

FACT_EXTRACTION_PROMPT = """You read a user's message and pull out lasting facts about them.

Reply with ONLY a JSON array. Each item looks like: {"key": "...", "value": "..."}

Rules:
1. Use one of these key names whenever it fits:
   name, age, city, country, job, employer, college, course, year_of_study,
   hobby, favourite_food, favourite_sport, favourite_colour, language,
   dietary_preference, pet, goal, project, birthday
   Only invent a new key (lowercase, underscores) if none of these fit.
2. Only record facts about THE USER that stay true over time.
3. Ignore questions, greetings, and passing comments.
4. If the message contains no lasting fact, reply with exactly: []

Examples:
Message: "Hi, I'm Swaraj and I live in Pune"
Reply: [{"key": "name", "value": "Swaraj"}, {"key": "city", "value": "Pune"}]

Message: "What did I tell you about my college?"
Reply: []

Message: "I moved to Mumbai last month for a new job at Infosys"
Reply: [{"key": "city", "value": "Mumbai"}, {"key": "employer", "value": "Infosys"}]

Message: "The weather is nice today"
Reply: []
"""


class ChatEngine:
    def __init__(self, session_id="session-1", memory=None, llm=None):
        self.session_id = session_id
        self.memory = memory or MemoryManager()
        self.llm = llm or LLMClient()

        # Working memory: the last few messages, kept exactly as written.
        # This is a plain list in memory, so it is emptied when a new session
        # starts. That is deliberate - it is how we prove that anything the bot
        # still remembers afterwards came from the database, not from here.
        self.working_memory = []

        # Details of the most recent turn, shown in the interface panel.
        self.last_turn = {}

    # -----------------------------------------------------------------------
    # Step 1: find facts in the message
    # -----------------------------------------------------------------------
    def extract_facts(self, message):
        """
        Ask the model which lasting facts are in this message.

        Returns a list of {"key", "value"} dictionaries. If the model cannot be
        reached, returns an empty list rather than raising, so a network problem
        cannot stop the conversation.
        """
        try:
            result = self.llm.chat_json([
                {"role": "system", "content": FACT_EXTRACTION_PROMPT},
                {"role": "user", "content": message},
            ])
        except LLMError:
            return []

        # The model should return a list, but occasionally returns a single
        # object. Accept both rather than failing.
        if isinstance(result, dict):
            result = [result]
        if not isinstance(result, list):
            return []

        facts = []
        for item in result:
            if isinstance(item, dict) and item.get("key") and item.get("value"):
                facts.append({
                    "key": str(item["key"]),
                    "value": str(item["value"]),
                })
        return facts

    # -----------------------------------------------------------------------
    # Step 4: build the prompt
    # -----------------------------------------------------------------------
    def build_messages(self, message, memories):
        """
        Assemble what we send to the model.

        The retrieved memories go into the system message rather than being
        pretended to be part of the conversation. That keeps a clean line
        between what the user actually said and what we looked up for them.
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
            "- Keep replies under 80 words."
        )

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.working_memory[-config.WORKING_MEMORY_TURNS:])
        messages.append({"role": "user", "content": message})
        return messages

    # -----------------------------------------------------------------------
    # The whole turn
    # -----------------------------------------------------------------------
    def send(self, message):
        """
        Handle one user message and return (reply, details).

        `details` describes everything that happened internally, which is what
        the interface panel displays: which facts were found, which memories
        were retrieved and with what scores, and any contradiction resolved.
        """
        # 1 + 2: find facts and store them, noting anything they replaced.
        facts = self.extract_facts(message)
        stored_facts = []
        contradictions = []

        for fact in facts:
            new_record, replaced = self.memory.remember_fact(
                fact["key"], fact["value"], self.session_id
            )
            stored_facts.append({
                "id": new_record["id"],
                "key": new_record["metadata"]["key"],
                "value": new_record["metadata"]["value"],
            })
            if replaced is not None:
                contradictions.append({
                    "key": replaced["metadata"]["key"],
                    "old_value": replaced["metadata"]["value"],
                    "new_value": new_record["metadata"]["value"],
                    "old_id": replaced["id"],
                    "new_id": new_record["id"],
                })

        # 3: search memory for anything relevant to this message.
        memories = self.memory.recall(message)

        # 4: ask the model, using those memories.
        messages = self.build_messages(message, memories)
        try:
            reply = self.llm.chat(messages)
            model_used = config.LLM_MODEL
        except LLMError as error:
            # If the model is unreachable we still answer from memory alone,
            # so the memory features can be demonstrated without a connection.
            model_used = "unavailable"
            if memories:
                reply = (
                    "I cannot reach the language model right now, but here is "
                    "what I have stored:\n"
                    + "\n".join("- " + memory["text"] for memory in memories)
                )
            else:
                reply = "I cannot reach the language model right now (%s)." % error

        # 5: save the message itself, then trim if the store has grown large.
        self.memory.remember_message(message, self.session_id)
        pruned = self.memory.prune()

        self.working_memory.append({"role": "user", "content": message})
        self.working_memory.append({"role": "assistant", "content": reply})

        self.last_turn = {
            "facts_found": stored_facts,
            "contradictions": contradictions,
            "memories_used": memories,
            "pruned_count": len(pruned),
            "model": model_used,
            "tokens_used": self.llm.total_tokens,
            "summary": self.memory.summary(),
        }
        return reply, self.last_turn

    def start_new_session(self, session_id):
        """
        Begin a fresh session.

        Clearing working_memory is the whole point: from here on, anything the
        bot recalls must have come out of the database. This is what
        demonstrates memory that lasts beyond a single conversation.
        """
        self.session_id = session_id
        self.working_memory = []
