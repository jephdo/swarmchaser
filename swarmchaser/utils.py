from datetime import timezone
from datetime import datetime, timedelta

# https://codereview.stackexchange.com/a/217074
def levenshtein_distance(str1, str2):
    counter = {"+": 0, "-": 0}
    distance = 0
    for edit_code, *_ in ndiff(str1, str2):
        if edit_code == " ":
            distance += max(counter.values())
            counter = {"+": 0, "-": 0}
        else:
            counter[edit_code] += 1
    distance += max(counter.values())
    return distance


def humanize_date(time=False):
    """Get a datetime object or a int() Epoch timestamp and return a
    pretty string like 'an hour ago', 'Yesterday', '3 months ago',
    'just now', etc
    """
    now = datetime.now()
    if type(time) is int:
        diff = now - datetime.fromtimestamp(time)
    elif isinstance(time, datetime):
        diff = now - time
    elif not time:
        diff = 0
    second_diff = diff.seconds
    day_diff = diff.days

    if day_diff < 0:
        return ""

    if day_diff == 0:
        if second_diff < 10:
            return "just now"
        if second_diff < 60:
            return str(second_diff) + " seconds ago"
        if second_diff < 120:
            return "a minute ago"
        if second_diff < 3600:
            return str(second_diff // 60) + " minutes ago"
        if second_diff < 7200:
            return "an hour ago"
        if second_diff < 86400:
            return str(second_diff // 3600) + " hours ago"
    if day_diff == 1:
        return "Yesterday"
    if day_diff < 7:
        return str(day_diff) + " days ago"
    if day_diff < 31:
        return str(day_diff // 7) + " weeks ago"
    if day_diff < 365:
        return str(day_diff // 30) + " months ago"
    return str(day_diff // 365) + " years ago"


def description_generator(release: dict) -> str:
    contents = []

    contents.append(
        f"[size=4][b]{release['artists_sort']} - {release['title']}[/b][/size]\n\n"
    )
    contents.append(
        f"[b]Label/Cat#:[/b] {release['labels'][0]['name']} / {release['labels'][0]['catno']}\n"
    )
    contents.append(f"[b]Country:[/b] {release.get('country')}\n")
    contents.append(f"[b]Year:[/b] {release['year']}\n")

    genres = ", ".join(release["genres"])
    contents.append(f"[b]Genre:[/b] {genres}\n")

    contents.append("\n")
    contents.append("[size=3][b]Tracklist[/b][/size]\n")

    tracklist = release["tracklist"]
    for track in tracklist:
        contents.append(f"[b]{track['position']}.[/b] {track['title']}")
        if track["duration"]:
            contents.append(f" [i]({track['duration']})[/i]")
        contents.append("\n")

    total_duration = sum_track_duration(
        t["duration"] for t in tracklist if t["duration"]
    )
    if total_duration:
        contents.append(f"[b]Total length:[/b] {total_duration}")
    contents.append(f"\n\nMore information: [url]{release['uri']}[/url]")

    return "".join(contents)


def sum_track_duration(durations: list[str]) -> int:
    total_duration = timedelta()

    for i in durations:
        if i.count(":") == 0:
            s = i
            m = 0
            h = 0
        elif i.count(":") == 1:
            (m, s) = i.split(":")
            h = 0
        elif i.count(":") == 2:
            (h, m, s) = i.split(":")
        else:
            raise
        d = timedelta(hours=int(h), minutes=int(m), seconds=int(s))
        total_duration += d
    return total_duration


def parse_genres(genres: str) -> tuple[str]:
    potential_separators = "|,/"

    for separator in potential_separators:
        if separator in genres:
            break
    else:
        separator = None

    if separator:
        genres = genres.split(separator)
    else:
        genres = [genres]

    return tuple(map(format_genre, genres))


def format_genre(genre: str) -> str:
    if genre == "Folk, World, & Country":
        return ""
    formatted = genre.strip().lower().replace(".", "").replace(" ", ".")

    return formatted
