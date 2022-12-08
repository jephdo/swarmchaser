import click
import logging
import dataclasses

from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.pretty import pprint

from swarmchaser import swarmchaser as sc
from swarmchaser import utils
from swarmchaser import models
from swarmchaser.config import config


@click.group()
@click.option("-d", "--debug/--no-debug", default=False)
def cli(debug):
    config.DEBUG = debug

    models.Base.metadata.create_all(models.engine)

    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=logging.DEBUG if config.DEBUG else logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
    )


@cli.command()
@click.option("-q", "--query")
@click.option("-t", "--tracker", default="rutracker")
@click.option("-f", "--format", default="WEB")
@click.option("-y", "--year", type=int, default=datetime.now().year)
@click.option("-l", "--limit", type=int, default=None)
@click.option("--insert/--no-insert", default=True)
def search(query, tracker, format, year, limit, insert):
    jackett = sc.Jackett(config.JACKETT_URL, config.JACKETT_API_KEY, tracker)
    query = f"{format} {year}"
    torrents = jackett.search(query)

    if limit:
        torrents = torrents[:limit]

    if insert:
        models.insert_torrents(models.engine, torrents)


@cli.command()
def refresh():
    models.update_eligibility()


@cli.command()
def status():
    session = models.create_session(models.engine)

    eligible_states = (models.TorrentStatus.eligible, models.TorrentStatus.downloaded)
    torrents = session.query(models.Torrent).filter(
        models.Torrent.status.in_(eligible_states)
    )

    table = Table(title="Torrent Status")
    table.add_column("ID")
    table.add_column("Release")
    table.add_column("Status")
    table.add_column("Discogs")
    table.add_column("Last Updated")
    for (i, torrent) in enumerate(torrents):
        table.add_row(
            str(torrent.id),
            torrent.releasename,
            torrent.status.name,
            str(torrent.rutracker_id),
            utils.humanize_date(torrent.last_updated),
        )

    console = Console()
    console.print(table)
    session.close()


@cli.command()
@click.option("-c", "--category", default="swarmchaser")
def download(category):
    qbt = sc.qBittorrent()
    session = models.create_session(models.engine)

    torrents = session.query(models.Torrent).filter(
        models.Torrent.status == models.TorrentStatus.eligible
    )

    successful = qbt.download(torrents, category)

    for torrent in successful:
        torrent.last_updated = int(datetime.now().timestamp())
        torrent.status = models.TorrentStatus.downloaded
    session.commit()
    session.close()


@cli.command()
@click.option("-l", "--limit", type=int, default=None)
@click.option("--verify/--no-verify", default=True)
@click.option("--id", type=int, default=None)
def upload(limit, verify, id):
    session = models.create_session(models.engine)

    if id:
        torrents = [
            session.query(models.Torrent).filter(models.Torrent.id == id).first()
        ]
        print(torrents[0].download_url)
    else:
        torrents = session.query(models.Torrent).filter(
            models.Torrent.status == models.TorrentStatus.downloaded
        )

    if verify:
        pass

    redacted = sc.Redacted(config.REDACTED_URL, config.REDACTED_API_KEY)
    for torrent in torrents:
        response = redacted.upload(torrent)

        if response["status"] == "success":
            torrent.status = models.TorrentStatus.uploaded
            torrent.last_updated = int(datetime.now().timestamp())

            torrentid = response["response"]["torrentid"]
            groupid = response["response"]["groupid"]
            logging.info(
                f"New torrent created at: https://redacted.ch/torrents.php?id={groupid}&torrentid={torrentid}"
            )

            qbt = sc.qBittorrent()
            new_torrent = redacted.edit_torrent(torrent)
            bytestring = new_torrent.read()
            new_torrent.seek(0)
            torrent.target_infohash = sc.infohash(bytestring)
            qbt.client.torrents_add(
                torrent_files=new_torrent, category="swarmchaser", tags="myupload"
            )

            qbt.client.torrents_delete(
                delete_files=False, torrent_hashes=torrent.source_infohash
            )
            logging.info("Torrent file added to qBittorrent")
        else:
            logging.warning(
                f"Failed to upload torrent: {torrent.releasename}\n\n\n{response.json()}\n"
            )

    session.commit()
    session.close()


@cli.command()
@click.argument("id", type=int)
@click.option("-a", "--album-description/--no-album-description", default=False)
def debug(id, album_description):
    session = models.create_session(models.engine)

    torrent = session.query(models.Torrent).filter(models.Torrent.id == id).first()

    redacted = sc.Redacted(config.REDACTED_URL, config.REDACTED_API_KEY)

    params = redacted.setup_params(torrent.discogs_release)
    if not album_description:
        del params["album_desc"]
    pprint(params)

    session.commit()
    session.close()


@cli.command()
@click.argument("id", type=int)
@click.argument("discog", type=int)
def set(id, discog):
    session = models.create_session(models.engine)

    torrent = session.query(models.Torrent).filter(models.Torrent.id == id).first()

    torrent.discogs_release_id = discog
    torrent.discogs_release = sc.Discogs().release(discog)

    session.commit()
    session.close()


@cli.command()
@click.argument("discog", type=int)
def discogs(discog):
    pprint(sc.Discogs().release(discog))


if __name__ == "__main__":
    cli()
