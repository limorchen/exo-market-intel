"""'Copy answer' button: copies an answer plus its source list, so the [P#] citations
still make sense when pasted into an email or a document.

Both formats go to the clipboard: formatted HTML (Gmail, Outlook and Word get real
tables, bold and lists) and plain text (for plain-text destinations)."""
import html
import json

import markdown
import streamlit.components.v1 as components

import index as idx


def _source_lines(sources):
    for label, c in sources or []:
        yield label, c, f"{c['title']}, p. {c['page']} | {idx.where_filed(c)}"


def answer_as_text(answer, sources):
    """The answer followed by one line per cited passage: label, title, page, Drive location, link."""
    lines = [answer.strip()]
    if sources:
        lines += ["", "Sources:"]
        for label, c, line in _source_lines(sources):
            lines.append(f"[{label}] {line}" + (f" | {c['link']}" if c.get("link") else ""))
    return "\n".join(lines)


def answer_as_html(answer, sources):
    """The same content as formatted HTML. Answer text and paper titles are escaped
    (the model's output and PDF titles are untrusted), then Markdown is rendered."""
    body = markdown.markdown(html.escape(answer.strip(), quote=False), extensions=["tables", "sane_lists"])
    if sources:
        items = []
        for label, c, line in _source_lines(sources):
            text = html.escape(line)
            if c.get("link"):
                text += f' | <a href="{html.escape(c["link"], quote=True)}">open in Drive</a>'
            items.append(f"<li><b>[{html.escape(label)}]</b> {text}</li>")
        body += "<p><b>Sources:</b></p><ul>" + "".join(items) + "</ul>"
    return ('<div style="font-family: Arial, sans-serif; font-size: 14px">'
            + body.replace("<table>", '<table border="1" cellpadding="4" style="border-collapse: collapse">')
            + "</div>")


def copy_button(answer, sources, label="📋 Copy answer"):
    """A button that copies the answer and its sources. Rendered in a small iframe, so
    it tries the Clipboard API (HTML + text) first and falls back to execCommand('copy')."""
    def js(s):
        return json.dumps(s).replace("</", "<\\/")  # a safe JS string literal inside <script>

    components.html(f"""
<style>
  body {{ margin: 0; font-family: "Source Sans Pro", "Source Sans 3", sans-serif; }}
  button {{ font: inherit; font-size: 14px; padding: 4px 12px; cursor: pointer;
           border: 1px solid rgba(49, 51, 63, 0.2); border-radius: 8px; background: #fff; color: rgb(49, 51, 63); }}
  button:hover {{ border-color: #0F6E8C; color: #0F6E8C; }}
  #msg {{ font-size: 13px; color: rgba(49, 51, 63, 0.6); margin-left: 8px; }}
</style>
<button id="copy" type="button">{label}</button><span id="msg"></span>
<script>
  const text = {js(answer_as_text(answer, sources))};
  const richHtml = {js(answer_as_html(answer, sources))};
  document.getElementById("copy").addEventListener("click", async () => {{
    // 1) A 'copy' event lets us set both formats; it works inside Streamlit's component
    //    iframe, where the async Clipboard API is often blocked by permissions.
    let ok = false;
    const onCopy = (e) => {{
      e.clipboardData.setData("text/html", richHtml);
      e.clipboardData.setData("text/plain", text);
      e.preventDefault();
      ok = true;
    }};
    document.addEventListener("copy", onCopy);
    try {{ document.execCommand("copy"); }} catch (e) {{}}
    document.removeEventListener("copy", onCopy);
    // 2) Otherwise the Clipboard API: both formats, then plain text only.
    if (!ok) {{
      try {{
        await navigator.clipboard.write([new ClipboardItem({{
          "text/html": new Blob([richHtml], {{type: "text/html"}}),
          "text/plain": new Blob([text], {{type: "text/plain"}}),
        }})]);
        ok = true;
      }} catch (e) {{}}
    }}
    if (!ok) {{
      try {{ await navigator.clipboard.writeText(text); ok = true; }} catch (e) {{}}
    }}
    document.getElementById("msg").textContent = ok ? "Copied ✓" : "Couldn't copy here; select the text and press Ctrl+C";
  }});
</script>
""", height=40)
