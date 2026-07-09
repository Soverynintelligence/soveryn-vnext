import os
from dataclasses import dataclass

import requests
from requests_oauthlib import OAuth1

_SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"
_TWEETS_URL = "https://api.twitter.com/2/tweets"

_ENV_VARS = (
    "X_BEARER_TOKEN",
    "X_API_KEY",
    "X_API_KEY_SECRET",
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
                values["X_API_KEY_SECRET"],
                values["X_ACCESS_TOKEN"],
                values["X_ACCESS_TOKEN_SECRET"],
            ),
            http=http,
        )

    def search_recent(self, query: str, since_id: str | None = None) -> list[Tweet]:
        params = {"query": query, "tweet.fields": "author_id"}
        if since_id is not None:
            params["since_id"] = since_id
        resp = self._http.get(
            _SEARCH_URL,
            params=params,
            headers={"Authorization": f"Bearer {self._bearer}"},
        )
        self._raise_for_status(resp)
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

    def create_tweet(self, text: str) -> str:
        return self._post_tweet({"text": text})

    def reply_tweet(self, text: str, in_reply_to: str) -> str:
        body = {"text": text, "reply": {"in_reply_to_tweet_id": in_reply_to}}
        return self._post_tweet(body)

    def _post_tweet(self, body: dict) -> str:
        auth = OAuth1(*self._oauth)
        resp = self._http.post(_TWEETS_URL, json=body, auth=auth)
        self._raise_for_status(resp)
        return resp.json()["data"]["id"]

    @staticmethod
    def _raise_for_status(resp) -> None:
        if 200 <= resp.status_code < 300:
            return
        title = resp.json().get("title", "?")
        raise XClientError(f"X API {resp.status_code}: {title}")
