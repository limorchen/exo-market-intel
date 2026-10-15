"""NurExone Papers Assistant — chat with the company's scientific-papers library.

Run:  streamlit run app.py --server.fileWatcherType poll
"""
import html
import logging
import re
import time

import streamlit as st

import assistant
from copy_button import copy_button
import config
import drive
import index as idx

st.set_page_config(page_title="Papers Assistant", page_icon="📚", layout="wide")


def paper_link(title, url):
    """Link that opens the paper in a new browser tab, so the chat page and the
    conversation stay where they are. Titles come from the papers, so they're escaped."""
    text = html.escape(title or "")
    if not url:
        return text
    return f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{text}</a>'


# ── Access control: Google sign-in, company accounts only ──────────────────────
def require_company_login():
    auth_configured = False
    try:
        auth_configured = "auth" in st.secrets
    except Exception:
        pass
    if not auth_configured:
        if config.get("ALLOW_NO_AUTH") == "1":  # local development only
            st.sidebar.warning("Sign-in disabled (ALLOW_NO_AUTH=1): Drive sync is off. Do not deploy like this.")
            return "local-dev"
        st.error("Sign-in is not configured. Add an [auth] section to .streamlit/secrets.toml (see README).")
        st.stop()

    if not st.user.is_logged_in:
        st.title("📚 NurExone Papers Assistant")
        st.write("Internal tool. Sign in with your company Google account. "
                 "The assistant searches only the papers you can already open in Google Drive.")
        if st.button("Sign in with Google", type="primary"):
            st.login()
        st.stop()

    email = (st.user.get("email") or "").lower()
    if not any(email.endswith("@" + d) for d in config.ALLOWED_EMAIL_DOMAINS):
        st.error(f"{email} is not a company account.")
        if st.button("Sign out"):
            st.logout()
        st.stop()
    return email


SIGN_IN_MESSAGES = {
    "expired": "Your Google sign-in has expired (Google limits it to about an hour). Please sign in again.",
    "before_sync": "Your Google sign-in expires in a few minutes, too soon to start a sync. "
                   "Sign in again, then click **Sync** right away: you'll have a full hour.",
    "sync_paused": "Sync paused because your Google sign-in was about to expire. Everything indexed so far "
                   "is saved. Sign in again and click **Sync** to continue where it stopped.",
}


def ask_to_sign_in_again(reason="expired"):
    """Full-page prompt to sign in again. Called from inside the sidebar (sync), it
    reruns first so the message is shown in the main area, not squeezed into the sidebar."""
    if st.session_state.get("signin_reason") != reason:
        st.session_state["signin_reason"] = reason
        st.rerun()
    st.title("📚 NurExone Papers Assistant")
    st.warning(SIGN_IN_MESSAGES[reason])
    if rep := st.session_state.get("last_sync"):
        st.caption(f"Last sync: {rep['indexed']} papers indexed"
                   + (f", {rep['remaining']} still to go." if rep.get("remaining") else "."))
    if st.button("Sign in again", type="primary"):
        for key in ("drive_listing", "signin_reason"):
            st.session_state.pop(key, None)
        st.logout()
    st.stop()


def signin_seconds_left():
    """Seconds until the Google sign-in (and its Drive access token) expires, or None if unknown."""
    try:
        return float(st.user.get("exp")) - time.time()
    except (TypeError, ValueError, AttributeError):
        return None


user_email = require_company_login()
if reason := st.session_state.get("signin_reason"):
    ask_to_sign_in_again(reason)
dev_mode = user_email == "local-dev"


# ── Index ──────────────────────────────────────────────────────────────────────
@st.cache_resource
def get_conn():
    conn = idx.connect()
    # Drop files the current rules exclude (plain-text files, EXCLUDE_FOLDERS) once per server start.
    idx.purge_excluded(conn)
    return conn


@st.cache_resource(max_entries=1)
def load_index(version):
    """Loaded once per index version and shared by all users. Only the latest version
    is kept, so an update doesn't leave the previous copy in memory."""
    return idx.Index(get_conn())


def index_version():
    return idx.version(get_conn())


def drive_service():
    try:
        token = st.user.tokens["access"]
    except Exception:
        st.error("Drive access isn't configured: add `expose_tokens = [\"access\"]` and the Drive scope "
                 "to the [auth] section of the secrets (see README).")
        st.stop()
    return drive.get_service(token)


LISTING_TTL_SECONDS = 20 * 60


def my_drive_files(force=False):
    """The papers this user can see in the Drive folder, listed with *their* access.
    Cached per session for 20 minutes."""
    cached = st.session_state.get("drive_listing")
    if cached and not force and time.time() - cached["at"] < LISTING_TTL_SECONDS:
        return cached["files"]
    if not config.DRIVE_FOLDER_ID:
        st.error("DRIVE_FOLDER_ID is not set (see README).")
        st.stop()
    try:
        with st.spinner("Checking which papers you can access in Google Drive…"):
            files = drive.list_papers(drive_service(), config.DRIVE_FOLDER_ID)
    except drive.SessionExpired:
        ask_to_sign_in_again()
    except drive.DrivePermissionNotGranted:
        st.title("📚 NurExone Papers Assistant")
        st.warning(f"You're signed in as **{user_email}**, but Google Drive access wasn't allowed. "
                   "Sign out, sign in again, and on Google's screen tick **“See and download all your "
                   "Google Drive files”** (the app only reads, as you).")
        if st.button("Sign out and try again", type="primary"):
            st.session_state.pop("drive_listing", None)
            st.logout()
        st.stop()
    except drive.NoFolderAccess:
        st.title("📚 NurExone Papers Assistant")
        st.error(f"You're signed in as **{user_email}**, and this account can't open the papers folder "
                 "in Google Drive. If you have another company account with access, switch to it; "
                 "otherwise ask the folder's owner to share it with you.")
        if st.button("Sign out / switch account", type="primary"):
            st.session_state.pop("drive_listing", None)
            st.logout()
        st.stop()
    idx.mark_seen(get_conn(), files)
    st.session_state.drive_listing = {"at": time.time(), "files": files}
    return files


SYNC_MIN_SIGNIN_SECONDS = 15 * 60   # don't start a sync with less sign-in time left than this
SYNC_STOP_SIGNIN_SECONDS = 2 * 60   # pause a running sync this close to expiry


def run_sync():
    left = signin_seconds_left()
    if left is not None and left < SYNC_MIN_SIGNIN_SECONDS:
        ask_to_sign_in_again("expired" if left <= 0 else "before_sync")
    files = my_drive_files(force=True)
    bar = st.sidebar.progress(0.0, text="Preparing…")

    def progress(i, n, name, detail=""):
        bar.progress(i / max(n, 1), text=f"Indexing {i}/{n}: {name[:40]}" + (f" — {detail}" if detail else ""))

    def should_stop():
        left = signin_seconds_left()
        return left is not None and left < SYNC_STOP_SIGNIN_SECONDS

    try:
        with st.spinner("Syncing with Google Drive…"):
            report = idx.sync_with_drive(get_conn(), drive_service(), files, progress, should_stop)
    except drive.SessionExpired:
        ask_to_sign_in_again()
    bar.empty()
    st.session_state["last_sync"] = report
    if report.get("paused"):
        ask_to_sign_in_again("sync_paused")


if dev_mode:
    library = load_index(index_version())
    n_pending = 0
else:
    my_files = my_drive_files()
    # First run on a fresh server (e.g. after a Streamlit Cloud restart): build the index.
    if index_version()[0] == 0 and my_files and "auto_synced" not in st.session_state:
        st.session_state["auto_synced"] = True
        st.info("Building the search index from Google Drive for the first time — this can take a few minutes.")
        run_sync()
    n_pending = len(idx.pending(get_conn(), my_files))
    library = idx.UserView(load_index(index_version()), {f["id"] for f in my_files})


# ── Session state ──────────────────────────────────────────────────────────────
def new_conversation():
    st.session_state.api_messages = []                 # full Claude history (append-only)
    st.session_state.chat = []                         # what the UI shows
    st.session_state.registry = assistant.SourceRegistry()


if "api_messages" not in st.session_state:
    new_conversation()


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("📚 Papers Assistant")
    st.caption(f"Signed in as {user_email}")
    if st.button("➕ New conversation", use_container_width=True):
        new_conversation()
        st.rerun()

    st.divider()
    n_docs = len(library.docs)
    no_text = [d for d in library.docs if not d["n_chars"]]
    st.metric("Papers you can search", n_docs)
    st.caption(f"{len(library):,} searchable passages · last update {index_version()[1] or '—'}")
    if n_pending:
        st.info(f"{n_pending} new or changed papers in Drive aren't searchable yet — click Sync.")
    if st.button("🔄 Sync with Google Drive", use_container_width=True, disabled=dev_mode,
                 help="Index new or changed papers from the Drive folder, using your own Drive access."):
        run_sync()
        st.rerun()
    if rep := st.session_state.get("last_sync"):
        st.success(f"Sync done: {rep['indexed']} indexed, {rep['total']} files visible to you in Drive"
                   + (f", {rep['duplicates']} identical copies linked instead of re-indexed" if rep.get("duplicates") else "")
                   + (f", {rep['removed']} long-deleted papers removed" if rep["removed"] else "")
                   + (f", {rep['excluded']} excluded files removed." if rep.get("excluded") else "."))
        if rep["failed"]:
            with st.expander(f"⚠️ {len(rep['failed'])} files failed"):
                for name, err in rep["failed"]:
                    st.write(f"**{name}** — {err}")
    if no_text:
        with st.expander(f"⚠️ {len(no_text)} papers without extractable text"):
            st.caption("Probably scanned PDFs. Run OCR on them (e.g. open with Google Docs, or Acrobat) and re-upload.")
            for d in no_text:
                st.markdown(f"- {paper_link(d['name'], d['link'])}  \n  📁 `{idx.where_filed(d)}`",
                            unsafe_allow_html=True)
    with st.expander("Browse library"):
        q = st.text_input("Filter by title or folder", key="lib_filter").lower()
        for d in library.docs:
            path = idx.where_filed(d)
            if not q or q in (d["title"] or "").lower() or q in path.lower():
                st.markdown(f"- {paper_link(d['title'] or d['name'], d['link'])}  \n  📁 `{path}`",
                            unsafe_allow_html=True)


# ── Chat ───────────────────────────────────────────────────────────────────────
CITE_RE = re.compile(r"\bP\d+\b")


def cited_sources(text, registry):
    seen = []
    for bracket in re.findall(r"\[([^\]]*)\]", text):
        for lab in CITE_RE.findall(bracket):
            if lab in registry.by_label and lab not in seen:
                seen.append(lab)
    return [(lab, registry.by_label[lab]) for lab in seen]


def render_sources(sources):
    """Cited papers with their Drive path (always visible), then the cited passages."""
    if not sources:
        return
    papers = {}
    for lab, c in sources:
        papers.setdefault(c["file_id"], []).append((lab, c))
    lines = []
    for items in papers.values():
        c = items[0][1]
        title = paper_link(c["title"], c.get("link"))
        cites = ", ".join(f"[{lab}] p.{x['page']}" for lab, x in items)
        lines.append(f"- {title}  \n  📁 `{idx.where_filed(c)}`  \n  {cites}")
    st.markdown(f"**📄 Papers cited ({len(papers)})** · links open in a new tab\n" + "\n".join(lines),
                unsafe_allow_html=True)
    with st.expander(f"📎 Cited passages ({len(sources)})", expanded=False):
        for lab, c in sources:
            st.markdown(f"**[{lab}]** {c['title']} — p.{c['page']}")
            st.caption(f"📁 {idx.where_filed(c)}")
            st.caption(c["text"][:600] + ("…" if len(c["text"]) > 600 else ""))


def render_activity(steps):
    if steps:
        with st.expander(f"🔍 Research steps ({len(steps)})", expanded=False):
            for s in steps:
                st.markdown(s)


st.title("📚 NurExone Papers Assistant")
if not st.session_state.chat:
    st.caption(
        "Ask in plain language — e.g. *“What do our papers report on intranasal delivery of MSC-derived "
        "exosomes in spinal cord injury models?”* The assistant may ask a follow-up question to focus the search, "
        "and every finding is cited to a paper and page."
    )
    if n_docs == 0:
        st.warning("The library index is empty. Use **Sync with Google Drive** in the sidebar.")

for turn in st.session_state.chat:
    with st.chat_message(turn["role"]):
        if turn["role"] == "assistant":
            render_activity(turn.get("steps"))
        st.markdown(turn["content"])
        if turn["role"] == "assistant":
            render_sources(turn.get("sources"))
            if not turn.get("failed"):
                copy_button(turn["content"], turn.get("sources"))

if prompt := st.chat_input("Ask about the papers…", disabled=n_docs == 0):
    st.session_state.chat.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    turn_start = len(st.session_state.api_messages)
    st.session_state.api_messages.append({"role": "user", "content": prompt})
    registry = st.session_state.registry
    steps, answer, failed = [], "", False

    with st.chat_message("assistant"):
        status = st.status("Thinking…", expanded=False)
        placeholder = st.empty()
        streamed = ""
        try:
            for kind, payload in assistant.respond(assistant.make_client(), st.session_state.api_messages,
                                                   library, registry):
                if kind == "text":
                    streamed += payload
                    placeholder.markdown(streamed + "▌")
                elif kind == "interim":
                    if payload.strip():
                        steps.append(f"💬 {payload.strip()}")
                        status.markdown(f"💬 {payload.strip()}")
                    streamed = ""
                    placeholder.empty()
                elif kind == "status":
                    steps.append(payload)
                    status.markdown(payload)
                    status.update(label=payload)
                elif kind == "done":
                    answer = payload
        except Exception as e:
            # Drop the failed turn so the history stays valid for the next question.
            del st.session_state.api_messages[turn_start:]
            logging.exception("Answering failed")  # full details go to the server log only
            answer, failed = f"⚠️ {assistant.friendly_error(e)}", True
        status.update(label=f"Done — {len(steps)} research steps" if steps else "Done", state="complete")
        placeholder.markdown(answer)
        sources = cited_sources(answer, registry)
        render_sources(sources)
        if not failed:
            copy_button(answer, sources)

    st.session_state.chat.append({"role": "assistant", "content": answer, "steps": steps, "sources": sources,
                                  "failed": failed})
