# Everlake server image: TrinityCore "forever" branch (advocaite/TrinityCore) for the WoW Forever client.
# Based on jibay442/forever_docker (GPL-2.0). The core is pinned to one commit so the server, the frozen client
# build and the extracted data always match; bump TC_COMMIT on purpose, never by accident.
#
# Stage 1: compile worldserver + bnetserver + extractors
# Stage 2: download the Forever database release (world + hotfixes)
# Stage 3: slim runtime image

ARG UBUNTU_VERSION=24.04

############################ build ############################
FROM ubuntu:${UBUNTU_VERSION} AS build

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates git cmake make gcc g++ clang \
        libmysqlclient-dev libssl-dev libbz2-dev libreadline-dev libncurses-dev libboost-all-dev \
    && rm -rf /var/lib/apt/lists/*

ARG TC_REPO=https://github.com/advocaite/TrinityCore.git
# forever branch 2026-11-08: client 1.60.1.70862 (realms on 70862; bnetserver also lets 70790 in, docker/entrypoint.sh)
ARG TC_COMMIT=2ae1313e9f89ba34103fee1400dc3d4222efd8c4
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
# TOOLS=1: also build mapextractor / vmap4extractor / vmap4assembler / mmaps_generator
ARG TOOLS=1
WORKDIR /src/TrinityCore/build
RUN cmake .. \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/trinitycore \
        -DTOOLS=${TOOLS} \
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
# Our login-database tables the core patches need, applied by the updater on start like the fork's own custom files
# (name reservation: docker/patches/0008). The other sql/everlake files are data and stay manual.
COPY sql/everlake/2026_11_07_09_auth_name_reservation.sql /src/TrinityCore/sql/custom/auth/
# worldserver's auto-setup imports TDB_full_*.sql from its working directory
COPY --from=tdb /tdb/ /opt/trinitycore/bin/
COPY docker/entrypoint.sh docker/extract.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/extract.sh \
    && mkdir -p /opt/trinitycore/data /opt/trinitycore/logs /opt/trinitycore/certs /opt/trinitycore/overrides

ENV LD_LIBRARY_PATH=/opt/trinitycore/lib
WORKDIR /opt/trinitycore/bin
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["worldserver"]
