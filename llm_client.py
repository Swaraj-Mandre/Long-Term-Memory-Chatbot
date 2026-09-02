"""
Talks to the language model.

The model is DeepSeek v4 Flash, served by AtlasCloud.

We use the official `openai` Python library here, but note what that does and
does not mean:

  - We are NOT calling OpenAI's models. Not one request goes to OpenAI.
  - OpenAI's "chat completions" request format became the standard that most
    providers copied, so their library can talk to any provider that follows
    it. AtlasCloud does.

The library is pointed at AtlasCloud by setting `base_url`. Switching to a
different provider later means changing the URL and model name in config.py
and nothing else in the project.

Why use the library rather than building the HTTP request by hand:
  - it retries automatically when a request fails for a temporary reason
  - it raises clear, separate errors for authentication, rate limits and
    connection problems, instead of one generic HTTP error
  - it sets its own headers correctly, which matters because AtlasCloud sits
    behind Cloudflare and Cloudflare rejects requests that look automated
"""

import openai

import config


class LLMError(Exception):
    """
    One error type for every way the model can fail.

    The rest of the project only needs to know "the model did not answer", so
    we catch the library's various error types here and re-raise them as this
    single error with a readable message.
    """


class LLMClient:
    """A thin wrapper around the chat-completions endpoint."""

    def __init__(self, api_key=None, base_url=None, model=None):
        self.model = model or config.LLM_MODEL

        # This is the line that points the OpenAI library at AtlasCloud
        # instead of at OpenAI.
        self.client = openai.OpenAI(
            api_key=api_key or config.LLM_API_KEY or "missing-key",
            base_url=base_url or config.LLM_BASE_URL,
            timeout=config.LLM_TIMEOUT_SECONDS,
            max_retries=2,
        )

        # Counters shown in the interface, so the demo can report its usage.
        self.total_calls = 0
        self.total_tokens = 0

    # -----------------------------------------------------------------------
    # The single request that every other method goes through
    # -----------------------------------------------------------------------
    def _send(self, messages, temperature, max_tokens):
        if not config.LLM_API_KEY:
            raise LLMError("No API key. Set ATLASCLOUD_API_KEY in your .env file.")

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
            )

        # Each of these is a genuinely different problem, so each gets its own
        # message. Knowing which one happened is what makes the failure fixable.
        except openai.AuthenticationError as error:
            raise LLMError(
                "The API rejected the key (401). The key may be missing "
                "inference permission, or the account may be out of credit. "
                "Details: %s" % error
            )
        except openai.PermissionDeniedError as error:
            raise LLMError("Access denied (403): %s" % error)
        except openai.NotFoundError as error:
            raise LLMError("Model '%s' was not found: %s" % (self.model, error))
        except openai.RateLimitError as error:
            raise LLMError("Too many requests (429). Wait and retry: %s" % error)
        except openai.APIConnectionError as error:
            raise LLMError("Could not reach the server. Check the network: %s" % error)
        except openai.APIError as error:
            raise LLMError("The API returned an error: %s" % error)

        # Record usage for the statistics panel.
        self.total_calls += 1
        if response.usage:
            self.total_tokens += response.usage.total_tokens

        # The reply text sits inside a list of choices. We always ask for one
        # answer, so we read the first.
        choice = response.choices[0]
        content = choice.message.content

        if not content:
            # This model thinks before it answers, and that thinking counts
            # against max_tokens. If the budget runs out during the thinking,
            # the answer comes back empty with no error at all. Rather than
            # letting that look like a mysterious blank reply, we say exactly
            # what happened and how to fix it.
            if choice.finish_reason == "length":
                reasoning_used = 0
                if response.usage and response.usage.completion_tokens_details:
                    reasoning_used = (
                        response.usage.completion_tokens_details.reasoning_tokens or 0
                    )
                raise LLMError(
                    "The model ran out of tokens while thinking and never "
                    "reached its answer (%d tokens went to reasoning, limit was "
                    "%d). Raise CHAT_MAX_TOKENS / EXTRACT_MAX_TOKENS in "
                    "config.py." % (reasoning_used, max_tokens)
                )
            raise LLMError("The model returned an empty reply.")

        return content

    # -----------------------------------------------------------------------
    # Public methods
    # -----------------------------------------------------------------------
    def chat(self, messages, temperature=None, max_tokens=None):
        """Ask the model for a normal text reply."""
        text = self._send(
            messages,
            config.CHAT_TEMPERATURE if temperature is None else temperature,
            config.CHAT_MAX_TOKENS if max_tokens is None else max_tokens,
        )
        return text.strip()

    def chat_json(self, messages):
        """
        Ask the model for JSON and return it as a Python object.

        Temperature is 0 here so the same message always produces the same
        facts. Creativity in this job would mean inventing details the user
        never said.

        We parse defensively because models often wrap JSON in explanation text
        or in a code fence, and a strict json.loads() would crash on that.
        """
        raw = self._send(
            messages, config.EXTRACT_TEMPERATURE, config.EXTRACT_MAX_TOKENS
        )
        return parse_json_from_text(raw)


def parse_json_from_text(raw):
    """
    Pull the first JSON value out of a model's reply.

    Handles the three shapes that actually turn up in practice:
      1. clean JSON
      2. JSON inside a ```json ... ``` code fence
      3. JSON with a sentence before or after it
    """
    import json

    text = raw.strip()

    # Case 2: remove a surrounding code fence if there is one.
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.lstrip().lower().startswith("json"):
                text = text.lstrip()[4:]
            text = text.strip()

    # Case 1: try parsing it as-is.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Case 3: find the outermost [ ... ] or { ... } and parse only that part.
    for open_char, close_char in (("[", "]"), ("{", "}")):
        start = text.find(open_char)
        end = text.rfind(close_char)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue

    raise LLMError("No JSON found in the model's reply: " + raw[:200])
