"""
build_website.py – one 250-line handy script with strange classes and methods to upload underhood data to Notion
It was made in one file on purpose! It will be a library when the official Notion API arrives.
"""
from dataclasses import dataclass, field
from datetime import timedelta, datetime
from json import loads
from os import environ
from pathlib import Path
from time import sleep
from typing import Dict, List, Set, Optional, Type, Union

import requests
from notion.block import (
    BasicBlock,
    BookmarkBlock,
    CollectionViewBlock,
    DividerBlock,
    EmbedBlock,
    ImageBlock,
    HeaderBlock,
    SubheaderBlock,
    TextBlock,
    QuoteBlock,
)
from notion.client import NotionClient
from notion.collection import NotionDate

TWEET_DATE_FORMAT = "%a %b %d %H:%M:%S +0000 %Y"
IMAGE_FORMATS = (".png", ".jpg", ".jpeg")


class TableOfContentsBlock(BasicBlock):
    _type = "table_of_contents"


def md_link(display: str, url: str) -> str:
    return f"[{display}]({url})"


@dataclass
class Tweet:
    @dataclass
    class TweetMedia:
        type: str
        shorten_url: str
        source_url: str

    @dataclass
    class TweetURL:
        shorten_url: str
        display_url: str
        source_url: str

    id: str
    ignore: bool
    date: datetime
    text: str
    quote: str
    urls: List[TweetURL]
    quote_urls: List[TweetURL]
    media: List[TweetMedia]
    mentions: List[str]
    hashtags: List[str]
    images: List[str]


@dataclass
class LocalConfig:  # 🇷🇺
    week_title: str = "Архив недели"
    links_title: str = "Ссылки"
    days: List[str] = field(
        default_factory=lambda: [
            "Понедельник",
            "Вторник",
            "Среда",
            "Четверг",
            "Пятница",
            "Суббота",
            "Воскресенье",
        ]
    )
    td = timedelta(hours=3)


@dataclass
class Author:
    username: str
    tweets: Dict
    topics: Optional[Set[str]] = None
    avatar: Optional[str] = None


class Underhood:
    def __init__(
        self, token_v2: str, cf_token: str, name: str, archive_slug: str, cf_id: str
    ):
        self.client = NotionClient(token_v2=token_v2)
        self.name = name
        self.local = LocalConfig()
        self.archive = self.client.get_block(f"https://www.notion.so/{archive_slug}")
        self.cf_url = f"https://api.cloudflare.com/client/v4/accounts/{cf_id}/workers/scripts/{name}"
        self.cf_headers = {
            "Authorization": f"Bearer {cf_token}",
            "Content-Type": "application/javascript",
        }

    def add_author(self, author: Author) -> None:
        author_page = AuthorPage(
            author=author, page=self.archive.collection.add_row(), local=self.local
        )
        author_page.write_page()
        self.update_urls(author.username, author_page.url.split("/")[-1])

    def update_urls(self, url: str, slug: str) -> None:
        text = requests.get(self.cf_url, headers=self.cf_headers).text
        lines = text.split("\n")
        lines[10] = f"{lines[10][:-2]}, '{url}':'{slug}'}};"
        text = "\n".join(lines)
        requests.put(self.cf_url, headers=self.cf_headers, data=text.encode("utf8"))


def dict_tweet(t: dict, td) -> Tweet:
    return Tweet(
        id=t["id_str"],
        ignore=t["full_text"].startswith(("@", "RT @")),
        text=t["full_text"],
        quote=t["quoted_status"]["full_text"]
        if t["is_quote_status"] and "quoted_status" in t
        else None,
        date=datetime.strptime(t["created_at"], TWEET_DATE_FORMAT) + td,
        mentions=[u["screen_name"] for u in t["entities"]["user_mentions"]],
        hashtags=t["entities"]["hashtags"],
        urls=[
            Tweet.TweetURL(u["url"], u["display_url"], u["expanded_url"])
            for u in t["entities"]["urls"]
        ],
        quote_urls=[
            Tweet.TweetURL(u["url"], u["display_url"], u["expanded_url"])
            for u in t["quoted_status"]["entities"]["urls"]
        ]
        if t["is_quote_status"] and "quoted_status" in t
        else [],
        media=[
            Tweet.TweetMedia(m["type"], m["url"], m["media_url_https"])
            for m in t["entities"]["media"]
        ]
        if "media" in t["entities"]
        else [],
        images=list(),  # could be from media, could be from URLs
    )


class AuthorPage:
    def __init__(
        self, author: Author, page: CollectionViewBlock, local: LocalConfig,
    ):
        self.page = page
        self.url = page.get_browseable_url()
        self.author = author
        self.local = local
        self.links = set()

    def add(
        self, o: Type, content: Optional[str] = None
    ) -> Union[CollectionViewBlock, EmbedBlock, BookmarkBlock]:
        b = BasicBlock
        while True:  # the simplest hack to avoid Notion HTTP errors
            try:
                b = (
                    self.page.children.add_new(o, title=content)
                    if content
                    else self.page.children.add_new(o)
                )
            except Exception:  # too broad but good enough to work
                sleep(5)
                continue
            break
        return b

    def process_tweet(self, t: Dict) -> Tweet:
        tweet = dict_tweet(t, self.local.td)
        if not tweet.ignore:
            for m in tweet.media:
                if m.type == "photo":
                    tweet.images.append(m.source_url)
                    tweet.text = tweet.text.replace(m.shorten_url, "")
            for u in tweet.urls:
                tweet.text = tweet.text.replace(
                    u.shorten_url, md_link(u.display_url, u.source_url)
                )
                if u.source_url.endswith(IMAGE_FORMATS):
                    tweet.images.append(u.source_url)
                elif not ("twitter.com" in u.source_url and "status" in u.source_url):
                    self.links.add(u.source_url)
            for n in tweet.mentions:
                tweet.text = tweet.text.replace(
                    f"@{n}", md_link(f"@{n}", f"https://twitter.com/{n}")
                )
            for h in tweet.hashtags:
                tweet.text = tweet.text.replace(
                    f"#{h}", md_link(f"#{h}", f"https://twitter.com/search?q=%23{h}")
                )
            for u in tweet.quote_urls:
                tweet.quote = tweet.quote.replace(
                    u.shorten_url, md_link(u.display_url, u.source_url)
                )

        return tweet

    def write_page(self) -> None:
        current_day = None
        self.page.set("format.page_icon", self.author.avatar)
        self.page.title, self.page.twitter, self.page.nedelia, self.page.temy = (
            f"@{self.author.username}",
            f"twitter.com/{self.author.username}",
            NotionDate(
                start=datetime.strptime(
                    self.author.tweets[0]["created_at"], TWEET_DATE_FORMAT
                ).date(),
                end=datetime.strptime(
                    self.author.tweets[-1]["created_at"], TWEET_DATE_FORMAT
                ).date(),
            ),
            self.author.topics,
        )
        self.add(TableOfContentsBlock).set("format.block_color", "gray")
        self.add(
            HeaderBlock, content=f"{self.local.week_title} @{self.author.username}"
        )

        for t in self.author.tweets:
            tweet = self.process_tweet(t)
            if tweet.ignore:
                continue
            if tweet.date.weekday() != current_day:
                current_day = tweet.date.weekday()
                self.add(SubheaderBlock, content=self.local.days[current_day])
                self.add(DividerBlock)
            self.add(
                TextBlock,
                content=md_link(
                    tweet.date.strftime("%H:%M"),
                    f"https://twitter.com/{self.author.username}/status/{tweet.id}",
                ),
            ).set("format.block_color", "gray")
            if tweet.quote:
                self.add(QuoteBlock, content=tweet.quote)
            if len(tweet.text):
                self.add(TextBlock, content=tweet.text)
            for i in tweet.images:
                self.add(ImageBlock).set_source_url(i)
            self.add(DividerBlock)

        self.add(HeaderBlock, content=self.local.links_title)
        for l in sorted(self.links):
            self.add(BookmarkBlock).set_new_link(l)


def main():
    underhood = Underhood(
        token_v2=environ["NOTION_TOKEN_V2"],
        name=environ["UNDERHOOD"],
        archive_slug=environ["ARCHIVE_SLUG"],
        cf_id=environ["CF_ID"],
        cf_token=environ["CF_TOKEN"],
    )
    underhood.add_author(
        Author(
            username=environ["AUTHOR"],
            tweets=loads(
                (Path("dump") / f"{environ['AUTHOR']}-tweets.json").read_text()
            )["tweets"],
            avatar=environ["AUTHOR_IMAGE"],
        )
    )


if __name__ == "__main__":
    main()
