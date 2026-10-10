"""
Sends blog drafts to Blogger, as DRAFTS (never live): you read them in Blogger, fix anything there, and press Publish yourself.

What it does, for a row of the blog_posts table:
  * converts the markdown to styled HTML (blog_html.to_html), labels it Daily or Weekly, and creates a Blogger DRAFT;
  * remembers Blogger's post id in the database, so a post is never created twice;
  * with force=True (a re-written draft) it updates the Blogger draft; if the post is already LIVE it is never touched;
  * sync_status() notices posts you have published in Blogger and marks them published in the database.

Needs these in .env (blogger_auth.py prints them): BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, BLOGGER_REFRESH_TOKEN, BLOGGER_BLOG_ID.
Blogger's API has no field for the "search description", so it is shown in the Telegram note for you to paste into the post settings.
Standard library only for the web calls.
"""
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("blogger")
API = "https://www.googleapis.com/blogger/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
NEEDED = ("BLOGGER_CLIENT_ID", "BLOGGER_CLIENT_SECRET", "BLOGGER_REFRESH_TOKEN", "BLOGGER_BLOG_ID")
_token = {"value": None, "expires": 0.0}


class BloggerError(Exception):
    pass


def configured() -> bool:
    return all(os.getenv(name) for name in NEEDED)


def _send(request: urllib.request.Request, what: str) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raise BloggerError(f"{what}: HTTP {error.code} {error.read().decode('utf-8', 'replace')[:300]}") from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise BloggerError(f"{what}: could not reach Google ({error})") from None


def access_token() -> str:
    """A short-lived token made from the refresh token (cached for most of its hour)."""
    if _token["value"] and time.time() < _token["expires"]:
        return _token["value"]
    data = urllib.parse.urlencode({"client_id": os.getenv("BLOGGER_CLIENT_ID"), "client_secret": os.getenv("BLOGGER_CLIENT_SECRET"),
                                   "refresh_token": os.getenv("BLOGGER_REFRESH_TOKEN"), "grant_type": "refresh_token"}).encode()
    reply = _send(urllib.request.Request(TOKEN_URL, data=data, method="POST"), "getting a Blogger access token")
    _token.update(value=reply["access_token"], expires=time.time() + int(reply.get("expires_in", 3600)) - 120)
    return _token["value"]


def _api(method: str, path: str, body=None, params=None) -> dict:
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    headers = {"Authorization": "Bearer " + access_token(), "Content-Type": "application/json"}
    data = json.dumps(body).encode("utf-8") if body is not None else None
    return _send(urllib.request.Request(url, data=data, method=method, headers=headers), f"Blogger {method} {path}")


def blog_id() -> str:
    return os.getenv("BLOGGER_BLOG_ID")


def editor_url(post_id: str) -> str:
    return f"https://www.blogger.com/blog/post/edit/{blog_id()}/{post_id}"


def labels_for(market_date: str) -> list:
    """A weekly post is dated a Saturday; every other post is a daily one."""
    return ["Weekly"] if date.fromisoformat(market_date).weekday() == 5 else ["Daily"]


def create_draft(title: str, html: str, labels: list) -> dict:
    return _api("POST", f"/blogs/{blog_id()}/posts", {"kind": "blogger#post", "title": title, "content": html, "labels": labels}, {"isDraft": "true"})


def update_post(post_id: str, title: str, html: str, labels: list) -> dict:
    return _api("PATCH", f"/blogs/{blog_id()}/posts/{post_id}", {"title": title, "content": html, "labels": labels})


def get_post(post_id: str) -> dict:
    return _api("GET", f"/blogs/{blog_id()}/posts/{post_id}", params={"view": "ADMIN"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save(client, row_id, values: dict) -> None:
    client.table("blog_posts").update(values).eq("id", row_id).execute()


def push_row(client, row: dict, update_existing: bool = False) -> dict:
    """Create (or, with update_existing, refresh) the Blogger DRAFT for one blog_posts row.
    Returns {'action': 'created' | 'updated' | 'already_sent' | 'live', 'edit_url': ...}."""
    from blog_html import to_html
    post_id = row.get("blogger_post_id")
    html, labels = to_html(row["body_markdown"]), labels_for(row["market_date"])
    if post_id and not update_existing:
        return {"action": "already_sent", "edit_url": editor_url(post_id)}
    if post_id:
        current = get_post(post_id)
        if str(current.get("status", "")).upper() == "LIVE":          # already published on Blogger: never overwrite a live post
            _save(client, row["id"], {"blogger_status": "LIVE", "published": True, "published_at": row.get("published_at") or _now(), "blogger_url": current.get("url")})
            return {"action": "live", "edit_url": editor_url(post_id)}
        update_post(post_id, row["title"], html, labels)
        _save(client, row["id"], {"blogger_status": "DRAFT", "sent_to_blogger_at": _now()})
        return {"action": "updated", "edit_url": editor_url(post_id)}
    created = create_draft(row["title"], html, labels)
    _save(client, row["id"], {"blogger_post_id": created["id"], "blogger_url": created.get("url"), "blogger_status": "DRAFT", "sent_to_blogger_at": _now()})
    return {"action": "created", "edit_url": editor_url(created["id"])}


def sync_status(client) -> int:
    """Mark posts you published in Blogger as published here. Returns how many were found live. Never raises for one bad post."""
    found = 0
    rows = client.table("blog_posts").select("id, market_date, blogger_post_id, published, published_at").eq("published", False).execute().data
    for row in rows:
        if not row.get("blogger_post_id"):
            continue
        try:
            current = get_post(row["blogger_post_id"])
        except BloggerError as error:
            log.warning("Could not check post %s on Blogger: %s", row["market_date"], error)
            continue
        if str(current.get("status", "")).upper() == "LIVE":
            _save(client, row["id"], {"blogger_status": "LIVE", "published": True, "published_at": current.get("published") or _now(), "blogger_url": current.get("url")})
            found += 1
    return found


def check() -> None:
    """python blogger_publish.py : proves the .env settings work (reads your blog's name, changes nothing)."""
    missing = [name for name in NEEDED if not os.getenv(name)]
    if missing:
        raise SystemExit("Missing in .env: " + ", ".join(missing))
    blog = _api("GET", f"/blogs/{blog_id()}")
    print(f"Connected. Blog: {blog.get('name')}  ({blog.get('url')}), {blog.get('posts', {}).get('totalItems', '?')} published post(s).")
    print("Drafts will be created here; nothing is published automatically.")


if __name__ == "__main__":
    try:
        check()
    except BloggerError as error:
        raise SystemExit(f"Could not connect: {error}")
