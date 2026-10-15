"""Read-only Google Drive access *as the signed-in employee*.

There is no service account and no stored credential: every call uses the access
token Google issued to the user at sign-in (scope drive.readonly), so the app can
only ever see what that person can already open in Drive.
"""
import fnmatch
import io

import google_auth_httplib2
import httplib2
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

import config

FOLDER_MIME = "application/vnd.google-apps.folder"
GDOC_MIME = "application/vnd.google-apps.document"

# Papers only: PDF, Word and Google Docs. Plain-text files (.txt, .log, .md) are
# skipped, since in practice they're software logs, licenses and notes, not papers.
SUPPORTED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    GDOC_MIME,
}


def is_excluded_folder(name):
    """True if a folder name matches one of the EXCLUDE_FOLDERS patterns (case-insensitive)."""
    name = name.lower()
    return any(fnmatch.fnmatch(name, pattern.lower()) for pattern in config.EXCLUDE_FOLDERS)


def is_excluded_path(folder_path):
    """True if any folder in a 'Literature/sub/subsub' path is excluded."""
    return any(is_excluded_folder(part) for part in (folder_path or "").split("/") if part)

FIELDS = "nextPageToken, files(id, name, mimeType, modifiedTime, webViewLink, size, md5Checksum)"


class SessionExpired(Exception):
    """The user's Google access token is no longer valid (they need to sign in again)."""


class NoFolderAccess(Exception):
    """The user can't open the papers folder."""


class DrivePermissionNotGranted(Exception):
    """The user signed in but didn't tick the Drive permission on Google's consent screen."""


def _scope_missing(e):
    """True for a 403 caused by the token lacking the Drive scope (vs. no access to the file)."""
    text = (getattr(e, "content", b"") or b"").decode("utf-8", "replace")
    return any(s in text for s in ("ACCESS_TOKEN_SCOPE_INSUFFICIENT", "insufficientPermissions",
                                   "insufficient authentication scopes"))


# Every Drive request gets a time limit and retries: without them, one stalled
# connection would leave a sync waiting forever on a single paper.
HTTP_TIMEOUT_SECONDS = 60
RETRIES = 3


def get_service(access_token):
    http = google_auth_httplib2.AuthorizedHttp(
        Credentials(token=access_token), http=httplib2.Http(timeout=HTTP_TIMEOUT_SECONDS))
    return build("drive", "v3", http=http, cache_discovery=False)


def _call(request):
    try:
        return request.execute(num_retries=RETRIES)
    except RefreshError as e:
        # Expired token: the Google client tries to refresh it, but the app holds no
        # refresh token (by design), so the user has to sign in again.
        raise SessionExpired() from e
    except HttpError as e:
        if e.resp.status == 401:
            raise SessionExpired() from e
        raise


def list_papers(service, folder_id):
    """All supported files under folder_id that this user can see, recursing into
    subfolders. Each file gets a 'folder' key with its Drive path, starting with the
    root folder's name (e.g. "Literature/spinal cord models/biomarkers")."""
    try:
        root = _call(service.files().get(fileId=folder_id, fields="id, name", supportsAllDrives=True))
    except HttpError as e:
        if e.resp.status == 403 and _scope_missing(e):
            raise DrivePermissionNotGranted() from e
        if e.resp.status in (403, 404):
            raise NoFolderAccess() from e
        raise

    out, queue, seen = [], [(folder_id, root.get("name", ""))], set()
    while queue:
        fid, path = queue.pop()
        if fid in seen:
            continue
        seen.add(fid)
        token = None
        while True:
            resp = _call(service.files().list(
                q=f"'{fid}' in parents and trashed = false",
                fields=FIELDS,
                pageSize=1000,
                pageToken=token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ))
            for f in resp.get("files", []):
                if f["mimeType"] == FOLDER_MIME:
                    if is_excluded_folder(f["name"]):
                        continue  # skip the whole subtree
                    queue.append((f["id"], f"{path}/{f['name']}" if path else f["name"]))
                elif f["mimeType"] in SUPPORTED_MIME:
                    f["folder"] = path
                    out.append(f)
            token = resp.get("nextPageToken")
            if not token:
                break
    return out


def download(service, file):
    """File bytes; Google Docs are exported as plain text."""
    if file["mimeType"] == GDOC_MIME:
        request = service.files().export_media(fileId=file["id"], mimeType="text/plain")
    else:
        request = service.files().get_media(fileId=file["id"], supportsAllDrives=True)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    try:
        while not done:
            _, done = downloader.next_chunk(num_retries=RETRIES)
    except RefreshError as e:
        raise SessionExpired() from e
    except HttpError as e:
        if e.resp.status == 401:
            raise SessionExpired() from e
        raise
    return buf.getvalue()
