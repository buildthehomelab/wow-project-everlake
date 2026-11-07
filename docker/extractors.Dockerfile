# Everlake extractor image: only TrinityCore's tools (mapextractor, vmap4extractor, vmap4assembler, mmaps_generator),
# from the same TC_COMMIT and docker/patches as the server image (Dockerfile), without the servers. It builds in a
# fraction of the server image's time, so an extractor patch can be used without rebuilding the worldserver.
#
#   docker build -f docker/extractors.Dockerfile -t everlake-extractors:latest .
#
# Used by scripts/extract-extra-map.sh (terrain for maps the client only gets by hotfix, such as 530).

ARG UBUNTU_VERSION=24.04

############################ build ############################
FROM ubuntu:${UBUNTU_VERSION} AS build

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates git cmake make gcc g++ clang \
        libmysqlclient-dev libssl-dev libbz2-dev libreadline-dev libncurses-dev libboost-all-dev \
    && rm -rf /var/lib/apt/lists/*

# keep these two in step with the Dockerfile
ARG TC_REPO=https://github.com/advocaite/TrinityCore.git
ARG TC_COMMIT=5206a7275f03dd2f6f2217fab9f67a4b232269fa
RUN git init -q /src/TrinityCore \
    && git -C /src/TrinityCore remote add origin "${TC_REPO}" \
    && git -C /src/TrinityCore fetch -q --depth 1 origin "${TC_COMMIT}" \
    && git -C /src/TrinityCore checkout -q FETCH_HEAD

COPY docker/patches/ /patches/
RUN for p in /patches/*.patch; do [ -e "$p" ] || continue; echo "applying $p"; git -C /src/TrinityCore apply "$p" || exit 1; done

# same CascLib read-only fallback as the Dockerfile (applied before the build here: one build only)
RUN sed -i 's|handle = open(szFileName, oflag \| O_LARGEFILE);|handle = open(szFileName, oflag \| O_LARGEFILE);\n        if(handle == -1 \&\& oflag == O_RDWR \&\& (errno == EROFS \|\| errno == EACCES))\n            handle = open(szFileName, O_RDONLY \| O_LARGEFILE);|' \
        /src/TrinityCore/dep/CascLib/src/common/FileStream.cpp \
    && grep -q "errno == EROFS" /src/TrinityCore/dep/CascLib/src/common/FileStream.cpp

ARG BUILD_JOBS=4
WORKDIR /src/TrinityCore/build
RUN cmake .. \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/trinitycore \
        -DSERVERS=0 \
        -DSCRIPTS=none \
        -DTOOLS=1 \
        -DWITH_WARNINGS=0 \
    && make -j"${BUILD_JOBS}" \
    && make install

############################ runtime ############################
FROM ubuntu:${UBUNTU_VERSION}

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates libmysqlclient21 libssl3t64 libbz2-1.0 libreadline8t64 libncurses6 \
        libboost-filesystem1.83.0 libboost-program-options1.83.0 libboost-regex1.83.0 \
        libboost-locale1.83.0 libboost-thread1.83.0 libboost-iostreams1.83.0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/trinitycore /opt/trinitycore
COPY docker/extract-extra-map.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/extract-extra-map.sh && mkdir -p /opt/trinitycore/data
ENV LD_LIBRARY_PATH=/opt/trinitycore/lib
WORKDIR /opt/trinitycore/bin
ENTRYPOINT ["/usr/local/bin/extract-extra-map.sh"]
