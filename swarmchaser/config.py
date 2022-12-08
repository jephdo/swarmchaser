import os

from dotenv import load_dotenv

load_dotenv()


class Config:

    DEBUG = True

    JACKETT_URL = os.getenv("JACKETT_URL")
    JACKETT_API_KEY = os.getenv("JACKETT_API_KEY")

    DISCOG_API_KEY = os.getenv("DISCOG_API_KEY")
    DISCOG_APPLICATION_NAME = "SwarmChaserApp/0.1"

    REDACTED_API_KEY = os.getenv("REDACTED_API_KEY")
    REDACTED_URL = "https://redacted.ch/ajax.php"
    REDACTED_SOURCE_VALUE = "RED"
    REDACTED_ANNOUNCE_URL = os.getenv("REDACTED_ANNOUNCE_URL")

    QBITTORENT_HOST = os.getenv("QBITTORRENT_HOST")
    QBITTORRENT_PORT = os.getenv("QBITTORRENT_PORT")
    QBITTORRENT_USERNAME = os.getenv("QBITTORRENT_USERNAME")
    QBITTORRENT_PASSWORD = os.getenv("QBITTORRENT_PASSWORD")

    SQLITE_DB = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "torrents.sqlite"
    )


config = Config()
