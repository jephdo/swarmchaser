import re
import functools
import json
import logging
import hashlib

from io import BytesIO
from urllib.parse import urljoin
from datetime import datetime
from dataclasses import dataclass
from collections import OrderedDict

import requests
import pyben
import discogs_client
import qbittorrentapi

from .config import config
from .exceptions import JackettException
from .models import Torrent
from .utils import parse_genres, format_genre, description_generator
from . import utils


@dataclass
class ReleaseName:
    artist: str
    album: str
    year: int
    genres: list[str]


def parse_releasename(releasename: str) -> ReleaseName:
    match = re.match(
        r"\((?P<genre>[A-Za-z\s,.-]*)\) \[(?P<format>[A-Z]*)\] (?P<artist>.*) - (?P<album>.*) - (?P<year>\d{4}), ",
        releasename,
    )

    if match is None:
        return None

    matches = match.groupdict()
    artist = matches["artist"]
    album = matches["album"]
    year = int(matches["year"])
    genres = parse_genres(matches["genre"])
    return ReleaseName(artist, album, year, genres)


@dataclass
class JackettResult:
    id: int
    releasename: str
    artist: str
    album: str
    year: int
    download_url: str
    create_date: int
    size: int
    genres: list[str]
    discogs_release_id: int = None

    def retrieve_infohash(self):
        response = requests.get(self.download_url)
        return infohash(response.content)


class Jackett:

    CATEGORY_CODE_AUDIO_LOSSLESS = 3040

    def __init__(self, baseurl: str, apikey: str, tracker: str):
        tracker = tracker.lower()
        self.url = urljoin(baseurl, f"/api/v2.0/indexers/{tracker}/results")
        self.apikey = apikey

    def search(self, query: str) -> [JackettResult]:
        json = self.fetch(query)
        return self.parse(json)

    def fetch(self, query: str) -> dict:
        params = {
            "apikey": self.apikey,
            "Category": self.CATEGORY_CODE_AUDIO_LOSSLESS,
            "Query": query,
        }

        response = requests.get(self.url, params=params)
        return response.json()

    def parse(self, json: dict) -> [JackettResult]:
        if "Results" not in json:
            raise JackettException(str(json))

        torrents = []

        for result in json["Results"]:
            if result["Seeders"] > 0:  # and result["Tracker"].lower() == tracker:
                releasename = result["Title"]
                release = parse_releasename(releasename)
                if release is None:
                    continue
                guid = result["Guid"]
                id_ = int(guid.split("?t=")[-1])
                download_url = result["Link"]
                try:
                    create_date = datetime.strptime(
                        result["PublishDate"], "%Y-%m-%dT%H:%M:%S%z"
                    )
                except ValueError:
                    continue
                create_date = int(create_date.timestamp())
                size = result["Size"]

                torrents.append(
                    JackettResult(
                        id_,
                        releasename,
                        release.artist,
                        release.album,
                        release.year,
                        download_url,
                        create_date,
                        size,
                        release.genres,
                    )
                )

        return torrents


class Discogs:

    application_name = config.DISCOG_APPLICATION_NAME

    def __init__(self, apikey: str = None):
        self.apikey = apikey or config.DISCOG_API_KEY
        self.client = discogs_client.Client(
            config.DISCOG_APPLICATION_NAME, user_token=config.DISCOG_API_KEY
        )

    def search(self, torrent: Torrent) -> int:
        results = self.fetch(torrent.search_query())
        discog_id = self.parse(results)

        return discog_id

    @functools.lru_cache
    def fetch(self, query: str) -> dict:
        results = self.client.search(query, type="release")

        return results

    def parse(self, results: dict) -> int:
        if results.count == 0:
            return None
        return results[0].id

    def release(self, id: int) -> dict:
        release = self.client.release(id)
        release.refresh()
        return release.data


class Redacted:
    def __init__(self, baseurl: str = None, apikey: str = None):
        self.url = baseurl or config.REDACTED_URL
        self.apikey = apikey or config.REDACTED_API_KEY

    @functools.lru_cache
    def search(self, query: str):
        headers = {"Authorization": self.apikey}
        params = {"action": "browse", "searchstr": query}

        response = requests.get(self.url, params=params, headers=headers)
        return response.json()

    def check_exists(self, torrent: Torrent) -> bool:
        json = self.search(torrent.search_query())
        num_torrents = self.parse_num_torrents(json)

        return num_torrents > 0

    def parse_num_torrents(self, results: dict) -> int:
        return len(results["response"]["results"])

    def upload(self, torrent: Torrent) -> dict:
        url = "https://redacted.ch/ajax.php?action=upload"

        params = self.setup_params(torrent.discogs_release)
        filename = f"{torrent.id}.torrent"
        torrent_buffer = self.edit_torrent(torrent)
        files = {"file_input": (filename, torrent_buffer)}
        headers = {"Authorization": config.REDACTED_API_KEY}

        response = requests.post(url=url, data=params, files=files, headers=headers)
        return response.json()

    def setup_params(self, release: dict) -> dict:
        params = RedactedAlbumParameters(release).setup_params()
        return params

    def edit_torrent(self, torrent: Torrent) -> BytesIO:
        torrent_maker = TorrentMaker(
            torrent.download_url,
            config.REDACTED_ANNOUNCE_URL,
            config.REDACTED_SOURCE_VALUE,
        )

        return torrent_maker.create()


class RedactedAlbumParameters:

    # This should always be set to 0
    # Music->0, Applications->1, E-Books->2, Audiobooks->3, etc.
    CATEGORY_TYPE = 0  # Music

    def __init__(self, release: dict):
        self.release = release

    def setup_params(self):
        params = {
            "category_type": self.CATEGORY_TYPE,
            "artists[]": self.artists,
            "importance[]": self.importance,
            "title": self.release["title"],
            "year": self.release["year"],
            "releasetype": self.releasetype,
            "remaster_year": self.release["year"],
            "format": "FLAC",
            "bitrate": "Lossless",
            "media": "WEB",
            "tags": self.tags,
            "image": self.image,
        }

        label, catno = self.retrieve_label()
        params["remaster_record_label"] = label
        if catno:
            params["remaster_catalogue_number"] = catno

        params["album_desc"] = description_generator(self.release)

        return params

    @property
    def artists(self):
        return [artist["name"] for artist in self.release["artists"]]

    @property
    def importance(self):
        # Main->1, Guest->2, Composer->3, etc.
        # TODO: fill this out more completely to include remixers, featured guests, etc.
        return [1 for artist in self.release["artists"]]

    @property
    def releasetype(self):
        # check release.formats['descriptions'] has Album or compilation
        return 1

    @property
    def tags(self):
        tags = ",".join(map(format_genre, self.release["genres"]))
        return tags

    @property
    def image(self):
        images = self.release["images"]

        for image in images:
            if image["type"] == "primary":
                return image["uri"]

        for image in images:
            if image["type"] == "secondary":
                return image["uri"]
        return None

    def retrieve_label(self):
        labels = self.release["labels"]
        for label in labels:
            name = label["name"]
            catno = label.get("catno")

            return (name, catno)
        return None


class TorrentMaker:
    def __init__(
        self, download_url: str, announce: str, source: str, private: bool = True
    ):
        self.download_url = download_url
        self.announce = announce
        self.source = source
        self.private = private

    def create(self) -> BytesIO:
        bytestring = self.retrieve_torrent(self.download_url)
        return self.edit_torrent(bytestring)

    def retrieve_torrent(self, url) -> bytes:
        response = requests.get(url)
        if len(response.content) == 0:
            raise JackettException(
                f"Torrent file can not be downloaded from Jackett. Empty response: {url}"
            )

        return response.content

    def edit_torrent(self, bytestring: bytes) -> BytesIO:
        buffer = BytesIO()

        torrent = self.setup_torrent(bytestring)
        buffer.write(pyben.benencode(torrent))
        buffer.seek(0)
        return buffer

    def setup_torrent(self, bytestring: bytes) -> dict:
        torrent, _ = pyben.bendecode(bytestring)

        new_torrent = {}
        new_torrent["announce"] = self.announce
        new_torrent["creation date"] = int(datetime.now().timestamp())

        info = torrent["info"].copy()
        info["private"] = int(self.private)
        info["source"] = self.source

        # Torrent hash requires keys to be ordered:
        ordered_info = OrderedDict()
        for key in sorted(info.keys()):
            ordered_info[key] = info[key]

        new_torrent["info"] = ordered_info

        return new_torrent


class qBittorrent:
    def __init__(
        self,
        host: str = None,
        port: int = None,
        username: str = None,
        password: str = None,
    ):
        self.client = qbittorrentapi.Client(
            host=host or config.QBITTORENT_HOST,
            port=port or config.QBITTORRENT_PORT,
            username=username or config.QBITTORRENT_USERNAME,
            password=password or config.QBITTORRENT_PASSWORD,
        )
        self.client.auth_log_in()

    def download(self, torrents: [Torrent], category: str):
        existing_torrents = self.retrieve_torrents(torrents)

        successful = []
        skipped = 0
        for torrent in torrents:
            if torrent.source_infohash in existing_torrents:
                skipped += 1
                continue

            response = requests.get(torrent.download_url)
            self.client.torrents_add(
                torrent_files=response.content,
                category=category,
                seeding_time_limit=0,
            )
            logging.info(f"Sending torrent to qBittorrent: {torrent.releasename}")
            successful.append(torrent)
        logging.info(
            f"Sent total of ({len(successful)}) torrents to qBittorrent. Skipped ({skipped}) existing torrents. "
        )
        return successful

    def retrieve_torrents(self, torrents: [Torrent]) -> dict:
        hashes = "|".join(t.source_infohash for t in torrents)

        torrents = self.client.torrents_info(torrent_hashes=hashes)
        return set(t.infohash_v1 for t in torrents)


def infohash(torrent: bytes) -> str:
    torrent, _ = pyben.bendecode(torrent)
    return hashlib.sha1(pyben.benencode(torrent["info"])).hexdigest()
