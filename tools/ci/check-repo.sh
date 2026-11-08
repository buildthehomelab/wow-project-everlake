#!/usr/bin/env bash
# Repo checks that need no network (CI runs this; run it by hand too): tools/ci/check-repo.sh
#   1. the core pin is the same in the Dockerfile, docker-compose.yml and .env.example
#   2. sql/everlake file names: YYYY_MM_DD_NN_<database>_<what>.sql, no date + number used twice
set -u
cd "$(dirname "$0")/../.." || exit 1
fail=0
err() { echo "error: $*"; fail=1; }

# 1. core pin
docker_pin="$(sed -nE 's/^ARG TC_COMMIT=([0-9a-f]{40})$/\1/p' Dockerfile)"
compose_pin="$(sed -nE 's/.*TC_COMMIT: \$\{TC_COMMIT:-([0-9a-f]{40})\}.*/\1/p' docker-compose.yml)"
env_pin="$(sed -nE 's/^TC_COMMIT=([0-9a-f]{40})$/\1/p' .env.example)"
[ -n "$docker_pin" ] || err "no 40-character ARG TC_COMMIT in the Dockerfile"
[ "$compose_pin" = "$docker_pin" ] || err "docker-compose.yml TC_COMMIT default ($compose_pin) is not the Dockerfile's ($docker_pin)"
[ "$env_pin" = "$docker_pin" ] || err ".env.example TC_COMMIT ($env_pin) is not the Dockerfile's ($docker_pin)"
echo "core pin: $docker_pin"

# 2. SQL file names
seen=""
for f in sql/everlake/*.sql; do
    name="$(basename "$f")"
    if ! [[ "$name" =~ ^(20[0-9]{2}_[01][0-9]_[0-3][0-9]_[0-9]{2})_(auth|world|characters[0-9]*|hotfixes[0-9]*)_[a-z0-9_]+\.sql$ ]]; then
        err "$f: name must be YYYY_MM_DD_NN_<auth|world|charactersN|hotfixesN>_<what>.sql"
        continue
    fi
    prefix="${BASH_REMATCH[1]}"
    case " $seen " in *" $prefix "*) err "$f: $prefix is used by another file";; esac
    seen="$seen $prefix"
done
echo "sql files: $(ls sql/everlake/*.sql | wc -l | tr -d ' ')"

# the Dockerfile copies some SQL files into the image by name: they must exist
for f in $(grep -oE 'sql/everlake/[A-Za-z0-9_./-]+\.sql' Dockerfile | sort -u); do
    [ -f "$f" ] || err "Dockerfile copies $f, which does not exist"
done

exit $fail
