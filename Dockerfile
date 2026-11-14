# Everlake server image: our core fork (buildthehomelab/wow-trinitycore-everlake, branch everlake: advocaite's "forever"
# plus the WoW Forever Bots module and the changes we took, see its docs/upstream-prs.md) for the WoW Forever client.
# Based on jibay442/forever_docker (GPL-2.0). The core is pinned to one commit so the server, the frozen client
# build and the extracted data always match; bump TC_COMMIT on purpose, never by accident.
#
# Stage 1: compile worldserver + bnetserver + extractors
# Stage 2: download the Forever database release (world + hotfixes)
# Stage 3: slim runtime image

ARG UBUNTU_VERSION=24.04
# The core commit and the bots switch, declared here so the build stage uses them and the runtime stage records them
# (/opt/trinitycore/image-build.env, checked by the entrypoint against the image tag it was started as).
# The live realms: our fork's everlake branch with the bots (b1ba6dfa: forever 2ae1313e + forever-bots + the 92 reviewed
# advocaite pull requests, fork PRs #4-#19, TrinityCore master batches A-K #23 #24 #26 #28-#35, Karrz v0.1.33 data #22 and
# scripts #25, build fix #27, Karrz v0.1.34 data #36, Ring of Law arena #37, bot module #38, bot dual names #39,
# the Wintergrasp condition fix #42 and greyed-out ruleset cards for offline realms #43, Karrz v0.1.35 with his whole core
# catch-up #45, the Karrz upstream check #44, the Zephras Isle scene NPC fix #48, Karrz's 37 git commits after 0.1.35 #47
# with the 0.1.35 gaps #52, pet Move To / Stay #49 and pet water pathing #50, name lookups that keep the surname #51 #53,
# Karrz v0.1.36 #54 with its gcc build fix 9a7fc384, and hunter pets on WoW Forever's rules #55 #56), the
# same commit the PTR builds (docker-compose.ptr.yml), so the live app and the PTR app build one identical image.
# Client 1.60.1.70938 (realms on 70938, sql/everlake/2026_11_14_10; bnetserver and the worldservers also let 70790, 70862 and 70888 in,
# docker/entrypoint.sh).
ARG TC_COMMIT=b1ba6dfab5c93dad38bba1c7afffe88bf8589204
# PLAYERBOTS=1: the WoW Forever Bots module (src/modules/PlayerbotV2; the core commit must have it, as the fork's
# everlake branch does since PR #2). 0 builds the core without bots.
ARG PLAYERBOTS=1

############################ build ############################
FROM ubuntu:${UBUNTU_VERSION} AS build

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates git cmake make gcc g++ clang \
        libmysqlclient-dev libssl-dev libbz2-dev libreadline-dev libncurses-dev libboost-all-dev \
    && rm -rf /var/lib/apt/lists/*

ARG TC_REPO=https://github.com/buildthehomelab/wow-trinitycore-everlake.git
ARG TC_COMMIT
RUN git init -q /src/TrinityCore \
    && git -C /src/TrinityCore remote add origin "${TC_REPO}" \
    && git -C /src/TrinityCore fetch -q --depth 1 origin "${TC_COMMIT}" \
    && git -C /src/TrinityCore checkout -q FETCH_HEAD

# Fixes not merged upstream yet (docker/patches/*.patch, applied in name order; the build fails if one no longer applies).
# docker/patches/playerbot/*.patch change the PlayerbotV2 module: applied only when the core has it (forever-bots).
COPY docker/patches/ /patches/
RUN for p in /patches/*.patch; do [ -e "$p" ] || continue; echo "applying $p"; git -C /src/TrinityCore apply "$p" || exit 1; done \
    && if [ -d /src/TrinityCore/src/modules/PlayerbotV2 ]; then \
        for p in /patches/playerbot/*.patch; do [ -e "$p" ] || continue; echo "applying $p"; git -C /src/TrinityCore apply "$p" || exit 1; done; fi

# BUILD_JOBS: lower it on small machines (GCC needs ~2 GB RAM per job on the biggest files)
ARG BUILD_JOBS=4
ARG PLAYERBOTS
# TOOLS=1: also build mapextractor / vmap4extractor / vmap4assembler / mmaps_generator
ARG TOOLS=1
WORKDIR /src/TrinityCore/build
RUN cmake .. \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/trinitycore \
        -DTOOLS=${TOOLS} \
        -DBUILD_PLAYERBOT_V2=${PLAYERBOTS} \
        -DWITH_WARNINGS=0 \
    && make -j"${BUILD_JOBS}" \
    && make install

# CascLib opens every CASC file O_RDWR on Linux, which fails (EROFS) on the read-only client mount used by the
# extractor service. Fall back to O_RDONLY: the extractors only read. (Separate layer: incremental rebuild only.)
RUN sed -i 's|handle = open(szFileName, oflag \| O_LARGEFILE);|handle = open(szFileName, oflag \| O_LARGEFILE);\n        if(handle == -1 \&\& oflag == O_RDWR \&\& (errno == EROFS \|\| errno == EACCES))\n            handle = open(szFileName, O_RDONLY \| O_LARGEFILE);|' \
        /src/TrinityCore/dep/CascLib/src/common/FileStream.cpp \
    && grep -q "errno == EROFS" /src/TrinityCore/dep/CascLib/src/common/FileStream.cpp \
    && make -j"${BUILD_JOBS}" \
    && make install

############################ database release ############################
FROM ubuntu:${UBUNTU_VERSION} AS tdb

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl p7zip-full \
    && rm -rf /var/lib/apt/lists/*

ARG TDB_URL=https://github.com/advocaite/TrinityCore/releases/download/forever-tdb-2026-10-14/TDB_full_forever_2026_10_14.7z
WORKDIR /tdb
RUN curl -fL --retry 3 -o tdb.7z "${TDB_URL}" \
    && 7z e -y tdb.7z '*.sql' -r \
    && rm tdb.7z \
    # the dump creates its views with DEFINER=`trinity`@`localhost`: as any other account (e.g. trinity@'%' in the
    # mysql container) that needs SUPER/SET_USER_ID and the import stops (error 1227). Without the clause the views
    # belong to the importing user.
    && sed -i -E 's#/\*!50013 DEFINER=`[^`]*`@`[^`]*` SQL SECURITY DEFINER \*/##' /tdb/*.sql \
    && ! grep -l 'DEFINER=' /tdb/*.sql \
    && ls -la /tdb

############################ world data ############################
# The Forever world import (docs/forever-import.md): update files from buildthehomelab/wow-everlake-world-data, pinned by
# commit (full SHA). Empty (the default) takes none. The files land in the world database, so they reach every realm
# that uses that database and every realm started from the image: set WORLD_DATA_COMMIT only in a compose project with
# its own world database and its own EVERLAKE_IMAGE_TAG (the PTR realm first), never on the shared default image.
FROM ubuntu:${UBUNTU_VERSION} AS worlddata

ARG DEBIAN_FRONTEND=noninteractive
ARG WORLD_DATA_REPO=https://github.com/buildthehomelab/wow-everlake-world-data.git
ARG WORLD_DATA_COMMIT=
RUN mkdir -p /world-data \
    && if [ -n "${WORLD_DATA_COMMIT}" ]; then \
        echo "${WORLD_DATA_COMMIT}" | grep -Eq '^[0-9a-f]{40}$' || { echo "WORLD_DATA_COMMIT: a full 40-character commit SHA"; exit 1; }; \
        apt-get update && apt-get install -y --no-install-recommends ca-certificates git && rm -rf /var/lib/apt/lists/* \
        && git init -q /src/world-data \
        && git -C /src/world-data remote add origin "${WORLD_DATA_REPO}" \
        && git -C /src/world-data fetch -q --depth 1 origin "${WORLD_DATA_COMMIT}" \
        && git -C /src/world-data checkout -q FETCH_HEAD \
        && [ -d /src/world-data/sql/world ] \
        && for f in /src/world-data/sql/world/*; do \
            [ -e "$f" ] || continue; \
            [ -f "$f" ] || { echo "world data: $f is not a file"; exit 1; }; \
            # update-file names only (YYYY_MM_DD_NN or _NNN, world_everlake_*); the runtime stage refuses any name the
            # image already has, so a world-data file can never replace one of the fork's update files
            case "$(basename "$f")" in [0-9][0-9][0-9][0-9]_[0-9][0-9]_[0-9][0-9]_[0-9][0-9]_world_everlake_*.sql|[0-9][0-9][0-9][0-9]_[0-9][0-9]_[0-9][0-9]_[0-9][0-9][0-9]_world_everlake_*.sql) ;; \
                *) echo "world data: unexpected file name $f"; exit 1 ;; esac; \
            cp "$f" /world-data/; \
        done \
        && ls -la /world-data; \
    fi

############################ runtime ############################
FROM ubuntu:${UBUNTU_VERSION}

ARG DEBIAN_FRONTEND=noninteractive
# mysql-client is required: the TrinityCore DB updater shells out to the `mysql` binary
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates tzdata mysql-client \
        libmysqlclient21 libssl3t64 libbz2-1.0 libreadline8t64 libncurses6 \
        libboost-filesystem1.83.0 libboost-program-options1.83.0 libboost-regex1.83.0 \
        libboost-locale1.83.0 libboost-thread1.83.0 libboost-iostreams1.83.0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/trinitycore /opt/trinitycore
# The updater looks for sql/ under the source directory baked in at build time
COPY --from=build /src/TrinityCore/sql /src/TrinityCore/sql
# Our login-database rows, applied by the updater on start like the fork's own custom files: the one ruleset card at
# login (Forever), the realms' client build (1.60.1.70938), and the TACT keys live Forever sends that the core lacks (tools/live-hotfixes/tact_keys.py). Name
# reservation's tables are the fork's own now (sql/custom/auth/2026_11_07_09 and 2026_11_09_00). The other
# sql/everlake files are data and stay manual.
COPY sql/everlake/2026_11_08_06_auth_one_ruleset.sql sql/everlake/2026_11_14_10_auth_realms_70938.sql \
     /src/TrinityCore/sql/custom/auth/
COPY sql/everlake/2026_11_08_07_hotfixes_forever_card.sql sql/everlake/2026_11_08_08_hotfixes_live_tact_keys.sql \
     sql/everlake/2026_11_12_00_hotfixes_ruleset_cards.sql \
     /src/TrinityCore/sql/custom/hotfixes/
# Our world rules as update files: dynamic respawn groups (quest targets, herb and ore nodes), and the same rule run
# again after Karrz 0.1.35 added and removed spawns, and once more after the live captures of core pin b5c98f7a added 82 spawns.
# Karrz 0.1.36 needs another pass, dated after its 2026_11_13_91 world file.
# (a new file runs on every realm; an older one runs again only when the updater applies it again).
COPY sql/everlake/2026_11_09_00_world_dynamic_respawn.sql sql/everlake/2026_11_13_00_world_dynamic_respawn_again.sql \
     sql/everlake/2026_11_13_01_world_dynamic_respawn_after_b5c98f7.sql \
     sql/everlake/2026_11_14_00_world_dynamic_respawn_after_karrz_0136.sql \
     /src/TrinityCore/sql/custom/world/
# The world import's update files (empty unless WORLD_DATA_COMMIT is set; see the worlddata stage). Each name must be
# new to the image: the fork names some of its own files world_everlake_* too, and a plain COPY would overwrite them.
COPY --from=worlddata /world-data/ /tmp/world-data/
RUN for f in /tmp/world-data/*; do \
        [ -e "$f" ] || continue; \
        b="$(basename "$f")"; \
        clash="$(find /src/TrinityCore/sql -name "$b" -print -quit)"; \
        [ -z "$clash" ] || { echo "world data: $b would replace $clash"; exit 1; }; \
        mv "$f" /src/TrinityCore/sql/custom/world/; \
    done \
    && rmdir /tmp/world-data
# worldserver's auto-setup imports TDB_full_*.sql from its working directory
COPY --from=tdb /tdb/ /opt/trinitycore/bin/
COPY docker/entrypoint.sh docker/extract.sh /usr/local/bin/
# What this image was built from: the entrypoint compares it with the tag it runs as (IMAGE_TAG), so an image built by
# the wrong app under a PTR tag (e.g. without the bots) says so at start instead of running quietly without them.
ARG TC_COMMIT
ARG PLAYERBOTS
ARG WORLD_DATA_COMMIT
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/extract.sh \
    && mkdir -p /opt/trinitycore/data /opt/trinitycore/logs /opt/trinitycore/certs /opt/trinitycore/overrides \
    && printf 'TC_COMMIT=%s\nPLAYERBOTS=%s\nWORLD_DATA_COMMIT=%s\n' "${TC_COMMIT}" "${PLAYERBOTS}" "${WORLD_DATA_COMMIT}" \
        > /opt/trinitycore/image-build.env

ENV LD_LIBRARY_PATH=/opt/trinitycore/lib
WORKDIR /opt/trinitycore/bin
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["worldserver"]
