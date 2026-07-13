import os
from dataclasses import dataclass

import requests
from requests_oauthlib import OAuth1

_SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"
_TWEETS_URL = "https://api.twitter.com/2/tweets"

_ENV_VARS = (
    "X_BEARER_TOKEN",
    "X_API_KEY",
    "X_API_SECRET",
    "X_ACCESS_TOKEN",
    "X_ACCESS_TOKEN_SECRET",
)


class XClientError(Exception):
    pass


@dataclass(frozen=True)
class Tweet:
    id: str
    author: str
    text: str
    url: str


class XClient:
    def __init__(self, bearer: str, oauth: tuple[str, str, str, str], http=None):
        self._bearer = bearer
        self._oauth = oauth
        self._http = http if http is not None else requests

    @classmethod
    def from_env(cls, http=None) -> "XClient":
        values = {}
        for name in _ENV_VARS:
            value = os.environ.get(name)
            if not value:
                raise XClientError(f"missing X_* env var: {name}")
            values[name] = value
        return cls(
            bearer=values["X_BEARER_TOKEN"],
            oauth=(
                values["X_API_KEY"],
                values["X_API_SECRET"],
                values["X_ACCESS_TOKEN"],
                values["X_ACCESS_TOKEN_SECRET"],
            ),
            http=http,
        )

    def search_recent(self, query: str, since_id: str | None = None) -> list[Tweet]:
        params = {"query": query, "tweet.fields": "author_id"}
        if since_id is not None:
            params["since_id"] = since_id
        try:
            resp = self._http.get(
                _SEARCH_URL,
                params=params,
                headers={"Authorization": f"Bearer {self._bearer}"},
            )
        except Exception as exc:
            raise XClientError(f"X API request failed: {type(exc).__name__}") from exc
        self._raise_for_status(resp)
        try:
            data = resp.json().get("data", [])
            return [
                Tweet(
                    id=item["id"],
                    author=item.get("author_id", ""),
                    text=item.get("text", ""),
                    url=f"https://x.com/i/web/status/{item['id']}",
                )
                for item in data
            ]
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise XClientError(
                f"X API returned malformed search response: {type(exc).__name__}"
            ) from exc

    def create_tweet(self, text: str) -> str:
        return self._post_tweet({"text": text})

    def reply_tweet(self, text: str, in_reply_to: str) -> str:
        body = {"text": text, "reply": {"in_reply_to_tweet_id": in_reply_to}}
        return self._post_tweet(body)

    def _post_tweet(self, body: dict) -> str:
        auth = OAuth1(*self._oauth)
        try:
            resp = self._http.post(_TWEETS_URL, json=body, auth=auth)
        except Exception as exc:
            raise XClientError(f"X API request failed: {type(exc).__name__}") from exc
        self._raise_for_status(resp)
        try:
            return resp.json()["data"]["id"]
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise XClientError(
                f"X API returned malformed post response: {type(exc).__name__}"
            ) from exc

    @staticmethod
    def _raise_for_status(resp) -> None:
        if 200 <= resp.status_code < 300:
            return
        # Capture the `detail` (and nested errors[].message), not just the
        # generic `title` — X's real reason ("duplicate content", "you cannot
        # reply to ...") lives in detail; the title alone ("Forbidden") is
        # undebuggable.
        title, detail = "?", ""
        try:
            body = resp.json()
            title = body.get("title", "?")
            detail = body.get("detail", "") or ""
            if not detail and isinstance(body.get("errors"), list) and body["errors"]:
                detail = body["errors"][0].get("message", "") or ""
        except (ValueError, AttributeError, TypeError):
            pass
        msg = f"X API {resp.status_code}: {title}"
        if detail:
            msg += f" — {detail}"
        raise XClientError(msg)
