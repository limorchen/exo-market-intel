"""The research assistant: Claude with tools over the papers index.

Claude decides each turn whether to ask the user a clarifying question or search.
It can search several times with refined queries, read around a passage, and list
the library, then answers citing passage labels like [P3]. Labels are stable for the
whole conversation, and the UI turns them into a source list with Drive links.
"""
import json

import anthropic

import config
from index import where_filed

SYSTEM_PROMPT = """You are the research assistant for NurExone's scientists. You answer questions using the company's own library of scientific papers, which you can reach only through your tools. NurExone develops exosome-based therapeutics (including drug-loaded exosomes for CNS and spinal-cord injury), so expect questions on extracellular vesicles, regeneration, neuroinflammation, delivery, manufacturing and related biology.

How to work:
- If a request is broad or ambiguous in a way that would change which papers matter (e.g. species or model system, disease indication, EV source, outcome measure, time frame), ask one short round of clarifying questions, offering concrete options. A quick exploratory search first often makes these questions sharper. Don't ask when the request is already clear enough to answer well; don't ask more than once before giving some findings.
- Search with several focused queries rather than one long one: use synonyms, abbreviations and specific terms (e.g. "MSC-EV", "small extracellular vesicles", "PTEN siRNA"). Use read_more when a passage is cut off or you need the methods or numbers around it.
- Base every finding on retrieved passages. Cite each claim with its passage label, e.g. [P3] or [P3, P7]. Never cite a label you did not receive from a tool, and never cite or describe papers from your general knowledge as if they were in the library. If you add background from general knowledge, mark it clearly as such and keep it brief.
- Report what the evidence actually is: the model (in vitro, which animal model, human), dose or n where given, and the effect size or key numbers. Point out conflicting results and limitations.
- If the library doesn't cover the question, say so plainly and say what you searched for. A short honest "not found" beats a stretched answer.

Format answers for scientists: a 1–3 sentence direct answer first, then the supporting findings grouped by theme or by paper, then gaps or suggested follow-up questions when useful. Be concise. Under each answer the interface automatically lists every cited paper with its Drive path and link, so don't repeat that list; mention a paper's Drive path in your text when the user asks where something is."""

TOOLS = [
    {
        "name": "search_papers",
        "description": (
            "Semantic + keyword search over the full text of the company's paper library. "
            "Returns the most relevant passages, each with a label like P12 to cite, the paper title and page. "
            "Run several searches with different phrasings for thorough coverage."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for, in natural language or keywords."},
                "paper_filter": {
                    "type": "string",
                    "description": "Optional: restrict to papers whose title, filename or Drive folder contains this text.",
                },
                "max_results": {"type": "integer", "description": "Passages to return, 1-15. Default 8."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "read_more",
        "description": "Return the text surrounding a passage you already have (the passages before and after it in the same paper).",
        "input_schema": {
            "type": "object",
            "properties": {"label": {"type": "string", "description": "Passage label, e.g. P12."}},
            "required": ["label"],
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "list_papers",
        "description": "List papers in the library (title, filename, folder, pages). Use for questions about what the library contains.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filter": {"type": "string", "description": "Optional text to match in title, filename or folder."},
            },
            "required": [],
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
]


class SourceRegistry:
    """Assigns conversation-stable labels (P1, P2, ...) to retrieved chunks."""

    def __init__(self):
        self.by_label = {}
        self.label_of = {}

    def label(self, chunk):
        cid = chunk["id"]
        if cid not in self.label_of:
            lab = f"P{len(self.label_of) + 1}"
            self.label_of[cid] = lab
            self.by_label[lab] = chunk
        return self.label_of[cid]


def _fmt_passage(label, c):
    weak = " [WEAK MATCH: may not be relevant]" if c.get("weak") else ""
    return f"[{label}]{weak} {c['title']} — p.{c['page']}\nDrive path: {where_filed(c)}\n{c['text']}"


def run_tool(name, args, index, registry):
    """Returns (result_text, status_line_for_ui). Raises ValueError on invalid input."""
    if not isinstance(args, dict):
        raise ValueError("tool input must be an object")

    if name == "search_papers":
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        flt = args.get("paper_filter") if isinstance(args.get("paper_filter"), str) else None
        k = args.get("max_results", 8)
        k = max(1, min(int(k), 15)) if isinstance(k, (int, float)) else 8
        hits = index.search(query, top_k=k, doc_filter=flt)
        status = f"🔎 Searched: “{query}”" + (f" in “{flt}”" if flt else "") + f" — {len(hits)} passages"
        if not hits:
            return "No matching passages.", status
        return "\n\n---\n\n".join(_fmt_passage(registry.label(c), c) for c in hits), status

    if name == "read_more":
        label = str(args.get("label", "")).strip().strip("[]").upper()
        chunk = registry.by_label.get(label)
        if chunk is None:
            raise ValueError(f"unknown label {label!r}; use a label returned by search_papers")
        parts = index.neighbors(chunk["id"], window=1)
        status = f"📖 Read around {label}: {chunk['title'][:70]}"
        return "\n\n---\n\n".join(_fmt_passage(registry.label(c), c) for c in parts), status

    if name == "list_papers":
        flt = (args.get("filter") or "").lower() if isinstance(args.get("filter"), str) else ""
        docs = [d for d in index.docs
                if not flt or flt in (d["title"] or "").lower() or flt in d["name"].lower() or flt in (d["folder"] or "").lower()]
        status = f"📚 Listed library" + (f" matching “{flt}”" if flt else "") + f" — {len(docs)} papers"
        lines = [f"- {d['title'] or d['name']} | path: {where_filed(d)} | {d['n_pages']} pages"
                 + ("  [NO TEXT EXTRACTED — likely a scanned PDF]" if not d["n_chars"] else "")
                 for d in docs[:300]]
        more = f"\n(+{len(docs) - 300} more; narrow with a filter)" if len(docs) > 300 else ""
        return (f"{len(docs)} papers:\n" + "\n".join(lines) + more) if docs else "No papers match.", status

    raise ValueError(f"unknown tool {name}")


def respond(client, messages, index, registry):
    """Run one assistant turn over `messages` (mutated in place, append-only).

    Yields ("text", str) for streamed text; ("interim", str) when the text streamed so
    far turned out to be a preamble to tool calls (the UI moves it out of the answer);
    ("status", str) for tool activity; and finally ("done", final_answer_text).
    """
    turn_text = []
    json_retries = 0
    for _ in range(12):  # max model calls per user turn
        turn_text = []
        try:
            with client.beta.messages.stream(
                model=config.CLAUDE_MODEL,
                max_tokens=32000,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
                output_config={"effort": config.CLAUDE_EFFORT},
                cache_control={"type": "ephemeral"},
                # On a safety-classifier decline, the API re-runs the request on a fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                for event in stream:
                    if event.type == "text":
                        turn_text.append(event.text)
                        yield "text", event.text
                response = stream.get_final_message()
            json_retries = 0
        except ValueError:
            # Tool input JSON the SDK couldn't parse at all: re-issue the turn (bounded).
            json_retries += 1
            if json_retries > 2:
                raise
            continue

        messages.append({"role": "assistant", "content": response.content})

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        notice = {"refusal": "\n\n_The model declined to continue this request._",
                  "max_tokens": "\n\n_Response was cut off (length limit)._"}.get(response.stop_reason)
        if notice or not tool_uses:
            if notice:
                turn_text.append(notice)
                yield "text", notice
            if tool_uses:
                # Close the dangling tool calls so the next user message is a valid turn.
                messages.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": b.id, "is_error": True, "content": "Not executed."}
                    for b in tool_uses]})
            break

        yield "interim", "".join(turn_text)
        results = []
        for block in tool_uses:
            try:
                text, status = run_tool(block.name, block.input, index, registry)
                yield "status", status
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": text})
            except Exception as e:
                results.append({"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                "content": json.dumps({"error": str(e)})})
        messages.append({"role": "user", "content": results})
    else:
        turn_text = ["_Stopped after too many search steps — try a narrower question._"]
        yield "text", turn_text[0]

    yield "done", "".join(turn_text)


CONTACT = "Please let Limor know."


def friendly_error(e):
    """A message colleagues can act on, instead of the raw API error."""
    ref = getattr(e, "request_id", None)
    ref = f" (reference: {ref})" if ref else ""
    if isinstance(e, anthropic.BadRequestError) and "credit balance" in str(e).lower():
        return f"The assistant is temporarily unavailable: the AI service account is out of credit. {CONTACT}"
    if isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return f"The assistant can't reach the AI service: its access key was rejected. {CONTACT}"
    if isinstance(e, anthropic.RateLimitError):
        return "The AI service is busy right now. Please try again in a minute."
    if isinstance(e, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return "Couldn't connect to the AI service. Please try again in a moment."
    if isinstance(e, anthropic.APIStatusError) and e.status_code >= 500:
        return f"The AI service had a temporary problem. Please try again in a moment{ref}."
    return f"Something went wrong while answering ({type(e).__name__}){ref}. If it keeps happening, {CONTACT[0].lower()}{CONTACT[1:]}"


def make_client():
    key = config.get("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
