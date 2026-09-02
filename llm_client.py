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
import debug_log


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
    def _send(self, messages, temperature, max_tokens, purpose="model call"):
        if not config.LLM_API_KEY:
            raise LLMError("No API key. Set ATLASCLOUD_API_KEY in your .env file.")

        # Print the exact request before sending it, so what the model actually
        # received is never a guess.
        debug_log.llm_request(purpose, self.model, temperature, max_tokens, messages)

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

        # Print the raw reply, including the model's internal reasoning. Seeing
        # the reasoning is what makes an empty answer understandable rather
        # than mysterious.
        debug_log.llm_response(
            content=content,
            reasoning=getattr(choice.message, "reasoning_content", None),
            usage=_usage_as_dict(response.usage),
            finish_reason=choice.finish_reason,
        )

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
            purpose="write a reply to the user",
        )
        return text.strip()

    def chat_stream(self, messages, temperature=None, max_tokens=None):
        """
        Ask for a reply and yield it in pieces as it arrives.

        Yields dictionaries, each one of:

            {"type": "thinking", "text": ...}  the model reasoning internally
            {"type": "token",    "text": ...}  a piece of the actual answer
            {"type": "end",      "usage": ..., "text": full answer}

        Worth knowing: this model reasons before it answers, and the reasoning
        streams first. Measured on a short question, reasoning began at 2.9
        seconds and the first word of the answer at 3.4 seconds. So the useful
        part of streaming here is not speed on short replies, it is being able
        to show honestly that the model is thinking rather than stalled.
        """
        if not config.LLM_API_KEY:
            raise LLMError("No API key. Set ATLASCLOUD_API_KEY in your .env file.")

        temperature = config.CHAT_TEMPERATURE if temperature is None else temperature
        max_tokens = config.CHAT_MAX_TOKENS if max_tokens is None else max_tokens

        debug_log.llm_request("write a reply, streamed", self.model,
                              temperature, max_tokens, messages)

        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                # Without this the final usage numbers are not sent.
                stream_options={"include_usage": True},
            )

            answer = []
            reasoning = []
            usage = None

            for chunk in stream:
                if chunk.usage:
                    usage = chunk.usage

                # The chunk carrying usage has no choices, so skip it here.
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                thinking = getattr(delta, "reasoning_content", None)
                if thinking:
                    reasoning.append(thinking)
                    yield {"type": "thinking", "text": thinking}

                if delta.content:
                    answer.append(delta.content)
                    yield {"type": "token", "text": delta.content}

        except openai.AuthenticationError as error:
            raise LLMError("The API rejected the key (401): %s" % error)
        except openai.APIConnectionError as error:
            raise LLMError("Could not reach the server: %s" % error)
        except openai.APIError as error:
            raise LLMError("The API returned an error: %s" % error)

        full = "".join(answer).strip()

        self.total_calls += 1
        if usage:
            self.total_tokens += usage.total_tokens

        debug_log.llm_response(
            content=full,
            reasoning="".join(reasoning) or None,
            usage=_usage_as_dict(usage),
            finish_reason="stop (streamed)",
        )

        if not full:
            raise LLMError(
                "The model streamed no answer. It most likely spent the whole "
                "token budget reasoning. Raise CHAT_MAX_TOKENS in config.py."
            )

        yield {"type": "end", "text": full, "usage": _usage_as_dict(usage)}

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
            messages, config.EXTRACT_TEMPERATURE, config.EXTRACT_MAX_TOKENS,
            purpose="find lasting facts in the message",
        )
        parsed = parse_json_from_text(raw)
        debug_log.as_json("parsed into", parsed)
        return parsed


def _usage_as_dict(usage):
    """
    Flatten the usage object into a plain dictionary for logging.

    Reasoning tokens live in a nested field, and pulling them out here means
    the logger does not need to know the shape of the API response.
    """
    if usage is None:
        return None

    reasoning = None
    details = getattr(usage, "completion_tokens_details", None)
    if details is not None:
        reasoning = getattr(details, "reasoning_tokens", None)

    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
        "reasoning_tokens": reasoning,
    }


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
