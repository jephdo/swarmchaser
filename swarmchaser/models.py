import enum
import logging

from datetime import datetime

from sqlalchemy.orm import declarative_base
from sqlalchemy import create_engine, Column, Integer, String, Enum, Boolean
from sqlalchemy.orm import sessionmaker
from sqlalchemy.types import JSON

from .config import config

Base = declarative_base()

engine = create_engine("sqlite:///" + config.SQLITE_DB)


def create_session(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    return session


class TorrentStatus(enum.Enum):
    tracked = 1
    eligible = 2
    downloaded = 3
    uploaded = 4
    ineligible = 10


def insert_torrents(engine, torrents):
    session = create_session(engine)
    added, skipped = 0, 0
    for torrent in torrents:
        if session.query(Torrent).filter(Torrent.rutracker_id == torrent.id).first():
            logging.debug(f"Torrent already exists: {torrent.releasename}")
            skipped += 1
            continue

        logging.info(f"Adding new candidate torrent to track: {torrent.releasename}")
        session.add(
            Torrent(
                rutracker_id=torrent.id,
                releasename=torrent.releasename,
                artist=torrent.artist,
                album=torrent.album,
                year=torrent.year,
                download_url=torrent.download_url,
                create_date=torrent.create_date,
                size=torrent.size,
                discogs_release_id=torrent.discogs_release_id,
                source_infohash=torrent.retrieve_infohash(),
                last_updated=int(datetime.now().timestamp()),
                status=TorrentStatus.tracked,
            )
        )
        added += 1

    session.commit()
    session.close()
    logging.info(f"Added ({added}) new torrents. Skipped ({skipped}) torrents.")


class Torrent(Base):
    __tablename__ = "torrents"

    id = Column(Integer, primary_key=True)
    rutracker_id = Column(Integer)
    releasename = Column(String)
    artist = Column(String)
    album = Column(String)
    year = Column(Integer)
    details = Column(String)
    download_url = Column(String)
    create_date = Column(Integer)
    size = Column(Integer)
    genres = Column(String)
    discogs_release_id = Column(Integer)
    discogs_release = Column(JSON)
    source_infohash = Column(String)
    target_infohash = Column(String)
    last_updated = Column(Integer)
    status = Column(Enum(TorrentStatus), default=TorrentStatus.tracked)
    exists_redacted = Column(Boolean, default=None)

    def search_query(self):
        return f"{self.artist} - {self.album} - {self.year}"

    def __repr__(self):
        return f"<Torrent(releasename={self.releasename}')>"


def update_eligibility():
    from .swarmchaser import Discogs, Redacted

    discogs, redacted = Discogs(), Redacted()

    session = create_session(engine)

    torrents = session.query(Torrent).filter(Torrent.status == TorrentStatus.tracked)

    updated, ineligible = 0, 0
    for torrent in torrents:
        assert torrent.status == TorrentStatus.tracked

        discogs_id = discogs.search(torrent)

        if discogs_id is None:
            torrent.status = TorrentStatus.ineligible
            logging.debug(
                f"Unable to identify Discogs release. Marking as ineligible: {torrent.releasename}"
            )
            ineligible += 1
            continue
        else:
            torrent.discogs_release_id = discogs_id
            release = discogs.release(discogs_id)
            assert release["artists"] is not None
            torrent.discogs_release = release

        can_upload = not redacted.check_exists(torrent)

        if not can_upload:
            logging.debug(
                f"Torrent already exists on Redacted. Marking as ineligible: {torrent.releasename}"
            )
            torrent.status = TorrentStatus.ineligible
            ineligible += 1
        else:
            torrent.status = TorrentStatus.eligible
            torrent.last_updated = int(datetime.now().timestamp())
            updated += 1

    session.commit()
    session.close()

    logging.info(
        f"Marked ({ineligible}) torrents as ineligible. Updated ({updated}) torrents as eligible to be uploaded."
    )
