#!/usr/bin/env python3
"""The world build's inputs, step 2 of 2 (docker-compose.tracker.yml, service tracker-world-sort; runs on every start
of the tracker app, after scripts/tracker-world-files.sh).

The realm's image keeps three kinds of file together in sql/custom/world. The replay wants to know whose each one is,
so this sorts the copy in /world/incoming, then puts it in place as /world/current:

    TDB_full_world_*.sql      the release dump
    core/sql/updates/world    the core's update files
    core/sql/custom/world     the core's own custom files
    data/                     the world-data files: the names of sql/world at the image's WORLD_DATA_COMMIT
    everlake/                 this repository's files: the ones the Dockerfile of this folder copies into
                              sql/custom/world (a file an older image got from a line since removed stays with the core's)
    source.txt                the image, its commits, the counts, and anything that did not match

Every file's content is the image's. The world-data repository is asked for names only (one download per commit, kept
in /world/cache), and each of its files is compared with the image's copy: a difference is said, never repaired.

Step 1 removed the set of the start before, and only the last line here puts one in place. So a problem, whatever
it is, is said and ends with exit 0 and no /world/current: the website does not depend on these files, and a replay
of files that are not the image's would be worse than none.
"""
import datetime
import fnmatch
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import urllib.request

WORLD = "/world"
INCOMING, CURRENT, CACHE = (os.path.join(WORLD, name) for name in ("incoming", "current", "cache"))
DOCKERFILE = "/everlake/Dockerfile"
# owner/name on GitHub of the repository the Dockerfile's worlddata stage reads (its WORLD_DATA_REPO)
REPO = os.environ.get("WORLD_DATA_REPO") or "buildthehomelab/wow-everlake-world-data"
IMAGE = os.environ.get("WORLD_IMAGE") or "the realm image"
REPLAY = ("python3 tools/tracker.py world replay --dump /world/current/TDB_full_world_*.sql --core /world/current/core "
          "--data /world/current/data --folder everlake=/world/current/everlake")


def say(message):
    print("[tracker-world] " + message, flush=True)


def give_up(message):
    say(f"WARNING: {message}: no replay inputs")
    shutil.rmtree(INCOMING, ignore_errors=True)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def world_data_files(commit):
    """{file name: sha256} of sql/world at `commit` of the world-data repository."""
    cache = os.path.join(CACHE, f"world-data-{commit}.json")
    if os.path.isfile(cache):
        with open(cache, encoding="utf-8") as handle:
            return json.load(handle)
    with urllib.request.urlopen(f"https://codeload.github.com/{REPO}/tar.gz/{commit}", timeout=120) as response:
        archive = response.read()
    found = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member in tar:
            parts = member.name.split("/")      # <repository>-<commit>/sql/world/<file>
            if member.isfile() and len(parts) == 4 and parts[1:3] == ["sql", "world"]:
                found[parts[3]] = hashlib.sha256(tar.extractfile(member).read()).hexdigest()
    os.makedirs(CACHE, exist_ok=True)
    for name in os.listdir(CACHE):              # one commit at a time is enough
        os.unlink(os.path.join(CACHE, name))
    with open(cache + ".part", "w", encoding="utf-8") as handle:
        json.dump(found, handle)
    os.replace(cache + ".part", cache)
    return found


def dockerfile_world_files(path):
    """Names (or patterns) of the sql/everlake files the Dockerfile copies into the image's sql/custom/world."""
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read().replace("\\\n", " ")
    except OSError:
        return None
    names = set()
    for line in text.splitlines():
        words = line.split()
        if words[:1] == ["COPY"] and words[-1].rstrip("/") == "/src/TrinityCore/sql/custom/world":
            names.update(os.path.basename(word) for word in words[1:-1] if word.startswith("sql/everlake/"))
    return names


def count(folder):
    return sum(name.lower().endswith(".sql") for _root, _dirs, names in os.walk(folder) for name in names)


def main():
    if not os.path.isfile(os.path.join(INCOMING, "image-build.env")):
        return say(f"nothing new was copied from {IMAGE} (the tracker-world-copy log says why): nothing to sort")
    with open(os.path.join(INCOMING, "image-build.env"), encoding="utf-8") as handle:
        built = dict(line.strip().split("=", 1) for line in handle if "=" in line)
    custom = os.path.join(INCOMING, "core", "sql", "custom", "world")
    data, own = os.path.join(INCOMING, "data"), os.path.join(INCOMING, "everlake")
    os.makedirs(data)
    os.makedirs(own)
    notes = []

    commit = built.get("WORLD_DATA_COMMIT", "")
    if commit:
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            return give_up(f"the image's WORLD_DATA_COMMIT is not a commit ({commit[:60]})")
        try:
            listed = world_data_files(commit)
        except Exception as error:      # the network, the archive, the cache: all end the same way
            return give_up(f"the file names of {REPO} at {commit[:8]} could not be fetched ({type(error).__name__}: {error}); they are needed to tell "
                           "the world-data files from the core's. Restart the app to try again")
        if not listed:
            return give_up(f"{REPO} at {commit[:8]} has no files in sql/world")
        for name, digest in sorted(listed.items()):
            path = os.path.join(custom, name)
            if not os.path.isfile(path):
                notes.append(f"{name}: in world data {commit[:8]}, not in the image")
                continue
            if sha256(path) != digest:
                notes.append(f"{name}: the image's copy differs from world data {commit[:8]} (the image's is kept)")
            os.replace(path, os.path.join(data, name))

    copied = dockerfile_world_files(DOCKERFILE)
    if copied is None:
        notes.append("the Dockerfile could not be read: this repository's own world files stay under core custom")
    present = sorted(name for name in os.listdir(custom) if os.path.isfile(os.path.join(custom, name)))
    for pattern in sorted(copied or ()):        # a file newer than the image is not in it yet: no match, no note
        for name in fnmatch.filter(present, pattern):
            if os.path.isfile(os.path.join(custom, name)):
                os.replace(os.path.join(custom, name), os.path.join(own, name))

    dumps = sorted(name for name in os.listdir(INCOMING) if name.startswith("TDB_full_world_") and name.endswith(".sql"))
    counts = [("core updates", count(os.path.join(INCOMING, "core", "sql", "updates", "world"))), ("core custom", count(custom)),
              ("data repository", count(data)), ("everlake", count(own))]
    with open(os.path.join(INCOMING, "source.txt"), "w", encoding="utf-8") as handle:
        handle.write(f"image: {IMAGE}\ncopied: {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M} UTC\n")
        handle.write("".join(f"{key}: {value}\n" for key, value in sorted(built.items())))
        handle.write(f"dump: {' '.join(dumps)}\n")
        handle.write("".join(f"{label}: {number} files\n" for label, number in counts))
        handle.write("".join(f"note: {note}\n" for note in notes))
        handle.write(f"replay: {REPLAY}\n")

    if os.path.isdir(CURRENT):                  # only when this step is run by hand twice: step 1 removes it
        shutil.rmtree(CURRENT)
    os.rename(INCOMING, CURRENT)
    say(f"/world/current: {IMAGE}, core {built.get('TC_COMMIT', '?')[:8]}, world data {commit[:8] or 'none'}: "
        + ", ".join(f"{number} {label}" for label, number in counts))
    for note in notes:
        say(f"WARNING: {note}")
    say(f"replay, inside the tracker container: {REPLAY}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:                  # a full disk, a bug: said, and no half-sorted set stays behind
        give_up(f"sorting stopped ({type(error).__name__}: {error})")
