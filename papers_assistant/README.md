# NurExone Papers Assistant

Internal chat tool for searching the company's scientific-papers library in Google Drive, in plain language. Each employee signs in with their own company Google account, and the tool only ever shows papers that person can already open in Drive.

You ask a question. The assistant may ask a short follow-up to narrow it (model system, indication, EV source, outcome). It then searches the library several times with different phrasings and answers with every finding cited to a paper and page (`[P3]`). Each answer has a **Sources** panel that links to the passage text and the file in Drive, and a **Research steps** panel that shows what it searched for.

## How it works

```
Google Drive folder ──(signed-in user's own access, read-only)──> extract text per page (PDF / Word / Google Docs; plain-text files and EXCLUDE_FOLDERS skipped)
        │
        ▼
  passages (~1,100 chars, never crossing a page) ──> local index (SQLite)
        │                                               ├─ BM25 keyword index    (exact terms: PTEN, CD63, BBB)
        │                                               └─ dense embeddings      (meaning: "how well did rats walk")
        ▼
  search = keyword + semantic, fused, then re-ranked by a cross-encoder
        │
        ▼
  Claude (Opus 5.5) with tools: search_papers · read_more · list_papers
  → asks clarifying questions or searches → answers citing only retrieved passages
```

Some design choices behind the "reliable findings" requirement:
- **Hybrid retrieval with re-ranking.** Scientific questions mix exact identifiers with paraphrase, and neither keyword nor vector search handles both well alone.
- **Grounded answers.** Claude can only cite passage labels a tool actually returned. The UI shows only the sources the answer actually cites. Weak matches are flagged to the model so it doesn't stretch them into findings, and it is told to say "not found" rather than guess.
- **Privacy.** Embedding and re-ranking run locally, so full papers never leave the server. Claude only sees the passages retrieved for each question.
- **Drive permissions are respected.** There is no service account, shared password or stored credential. At sign-in, Google gives the app a short-lived, read-only token for that user. The app lists the folder with it and filters every search, the library list and the sources to files in that user's own listing. The index itself is shared (that's what keeps search fast), but nobody sees results from a paper they can't open in Drive.
- **Scanned PDFs.** Papers with no extractable text are listed in the sidebar so someone can OCR them. Otherwise they'd be silently unsearchable.

## One-time setup (Google Cloud project `papers-assistant`)

### 1. Enable the Google Drive API
APIs & Services → Library → **Google Drive API** → Enable.

### 2. OAuth consent screen
APIs & Services → **OAuth consent screen** (in newer consoles: Google Auth Platform → Branding / Audience):
- User type / audience: **Internal**, so only nurexone.com accounts can sign in and no Google verification is needed.
- App name `Papers Assistant`, with your email as support and developer contact.
- Data access / scopes: add `.../auth/drive.readonly`, plus `openid`, `email` and `profile`.

### 3. OAuth client
APIs & Services → Credentials → **Create credentials → OAuth client ID** → *Web application*. Add these authorized redirect URIs:
- `http://localhost:8501/oauth2callback`
- `https://<your-app>.streamlit.app/oauth2callback` (after deploying)

Copy the client ID and client secret into the secrets.

### 4. Secrets
Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in the Anthropic API key, `DRIVE_FOLDER_ID` (the *Literature* folder), the `[auth]` block (client ID/secret, plus a random `cookie_secret`, e.g. `python -c "import secrets; print(secrets.token_hex(32))"`), and keep `expose_tokens` and the Drive scope as they are. The secrets file is git-ignored.

If Workspace restricts third-party apps, an admin may need to mark this internal app as trusted (Admin console → Security → API controls).

## Run locally (WSL)

```bash
cd papers_assistant
pip install -r requirements.txt
streamlit run app.py --server.fileWatcherType poll
```

Sign in, then click **Sync with Google Drive**. The first person to open the app on an empty index triggers the first full sync automatically.

To try it without Google, run `python build_index.py /path/to/pdfs` and then `ALLOW_NO_AUTH=1 streamlit run app.py` (local development only).

## Keeping the library up to date

- Syncing runs **as the person who clicks Sync**, with their Drive access. It adds new papers and re-indexes changed ones. The sidebar shows when there are papers in Drive that aren't indexed yet.
- A paper missing from one person's listing may just be one they can't see, so a sync never deletes on that basis. Papers that no signed-in user has seen in Drive for 60 days (`PRUNE_AFTER_DAYS`) are removed. Until then they're hidden from everyone anyway, because search only returns files in the searcher's own Drive listing.
- Google limits the sign-in token to about an hour. If it expires, the app asks the user to sign in again.

## Deploy (Render)

The app runs as a Render **Web Service** with a **persistent disk**, so the index and the search models survive restarts and deploys. Memory use with ~350 papers is about 0.8 GB, so use the **Standard** instance (2 GB). Free and Starter instances (512 MB, no disk) are too small.

**New → Web Service**, connect this GitHub repo, then:

| Setting | Value |
|---|---|
| Branch | the branch to deploy (Render redeploys on every push to it) |
| Root Directory | `papers_assistant` |
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `mkdir -p .streamlit && cp /etc/secrets/secrets.toml .streamlit/secrets.toml && streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true` |
| Instance Type | Standard (2 GB) |
| Health Check Path | `/_stcore/health` |

**Disk** (Advanced → Add Disk): mount path `/var/data`, size 1 GB.

**Environment variables:**

| Key | Value |
|---|---|
| `PYTHON_VERSION` | `3.12.7` |
| `PAPERS_INDEX_DB` | `/var/data/papers.db` |
| `MODEL_CACHE_DIR` | `/var/data/models` |

**Secret File** (Environment → Secret Files): filename `secrets.toml`, contents = your local `.streamlit/secrets.toml`, with `redirect_uri` changed to `https://<service-name>.onrender.com/oauth2callback`. The start command copies it to where Streamlit looks for it, so it's never in the repo.

**Google sign-in:** add `https://<service-name>.onrender.com/oauth2callback` to the OAuth client's *Authorized redirect URIs* (Google Auth Platform → Clients → Papers Assistant web).

**First run:** the first signed-in visitor triggers the initial index build from Drive (about 20–30 minutes for ~350 papers). After that, the index is on the disk and only Sync is needed. With a disk attached, Render runs a single instance and has a few seconds of downtime during each deploy.

## Settings

| Key | Default | Notes |
|---|---|---|
| `CLAUDE_MODEL` | `claude-opus-5-5` | |
| `CLAUDE_EFFORT` | `high` | `medium` is faster and cheaper; `xhigh` digs deeper |
| `EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | changing it requires deleting `index/papers.db` and re-syncing |
| `RERANK_MODEL` | `Xenova/ms-marco-MiniLM-L-6-v2` | |
| `ALLOWED_EMAIL_DOMAINS` | `nurexone.com` | comma-separated |
| `EXCLUDE_FOLDERS` | `FlowJo*` | Drive folders to skip with everything inside; comma-separated name patterns, case-insensitive, `*` = anything. Applied on the next app start or Sync |
| `PRUNE_AFTER_DAYS` | `60` | remove papers no signed-in user has seen in Drive for this long |
| `PAPERS_INDEX_DB` | `index/papers.db` | where the search index is stored (env var) |
| `MODEL_CACHE_DIR` | fastembed default (`/tmp`) | where the search models are downloaded; on a server, a persistent disk |

## Files

```
app.py          Streamlit UI: sign-in gate, chat, sources, Drive sync
assistant.py    Claude agent loop, system prompt, tools
index.py        chunking, embeddings, hybrid search + re-ranking, Drive sync, per-user filtering
drive.py        Google Drive listing / download, as the signed-in user
extract.py      PDF / DOCX / Google Doc / text extraction, title guessing
build_index.py  CLI indexer for a local folder (testing)
config.py       settings from st.secrets / env
```
