"""
ONE-TIME sign-in for the Blogger API. Run this on YOUR computer (it opens a browser), not on the VM:

    python blogger_auth.py client_secret.json

1. It opens Google's sign-in page. Sign in with the account that owns the blog and click Allow.
   (Because the app is your own and unverified, Google shows a warning: click Advanced, then "Go to ... (unsafe)".)
2. It prints your blogs (with their ids) and four lines to paste into the .env file, on your computer AND on the VM:
       BLOGGER_CLIENT_ID=...   BLOGGER_CLIENT_SECRET=...   BLOGGER_REFRESH_TOKEN=...   BLOGGER_BLOG_ID=...
The refresh token lets the app create drafts on your blog, so treat it like a password: only in .env, never in git, never in chat.
Uses only the Python standard library.
"""
import http.server
import json
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser

SCOPE = "https://www.googleapis.com/auth/blogger"


class Catcher(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" in query or "error" in query:
            self.server.result = {k: v[0] for k, v in query.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"<h3>Done. You can close this tab and go back to the terminal.</h3>")

    def log_message(self, *args):
        pass


def post_form(url: str, data: dict) -> dict:
    request = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python blogger_auth.py client_secret.json")
    app = json.load(open(sys.argv[1], encoding="utf-8"))
    app = app.get("installed") or app.get("web")
    if not app:
        raise SystemExit("This file does not look like an OAuth client file (it should start with {\"installed\": ...}). Create a 'Desktop app' client.")
    server = http.server.HTTPServer(("127.0.0.1", 0), Catcher)
    server.result = None
    redirect = f"http://127.0.0.1:{server.server_address[1]}"
    state = secrets.token_urlsafe(16)
    url = app["auth_uri"] + "?" + urllib.parse.urlencode({
        "client_id": app["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state})
    print("Opening your browser. If nothing opens, copy this address into it:\n" + url + "\n")
    webbrowser.open(url)
    while server.result is None:
        server.handle_request()
    result = server.result
    if "error" in result or result.get("state") != state:
        raise SystemExit(f"Sign-in failed: {result.get('error', 'the state did not match, try again')}")
    tokens = post_form(app["token_uri"], {"code": result["code"], "client_id": app["client_id"], "client_secret": app["client_secret"],
                                          "redirect_uri": redirect, "grant_type": "authorization_code"})
    if "refresh_token" not in tokens:
        raise SystemExit("Google gave no refresh token. Remove the app's access at myaccount.google.com/permissions and run this again.")
    request = urllib.request.Request("https://www.googleapis.com/blogger/v3/users/self/blogs", headers={"Authorization": "Bearer " + tokens["access_token"]})
    with urllib.request.urlopen(request, timeout=30) as response:
        blogs = json.loads(response.read()).get("items", [])
    print("Your blogs:")
    for blog in blogs:
        print(f"   id {blog['id']}   {blog['name']}   {blog.get('url', '')}")
    blog_id = blogs[0]["id"] if len(blogs) == 1 else "<pick the id of your blog from the list above>"
    print("\nPaste these four lines into .env (on this computer and on the VM). Keep them secret:\n")
    print(f"BLOGGER_CLIENT_ID={app['client_id']}")
    print(f"BLOGGER_CLIENT_SECRET={app['client_secret']}")
    print(f"BLOGGER_REFRESH_TOKEN={tokens['refresh_token']}")
    print(f"BLOGGER_BLOG_ID={blog_id}")


if __name__ == "__main__":
    main()
