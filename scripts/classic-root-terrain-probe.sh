#!/usr/bin/env bash
# Diagnostic for the shared terrain context, scoped to Classic realm 71.
set -euo pipefail

mode=${1:-check}
case "$mode" in check|apply|rollback) ;; *) echo "usage: $0 check|apply|rollback" >&2; exit 2;; esac
world=ix-everlake-realm2-worldserver2-1
mysql_classic() {
    docker exec -i ix-everlake-mysql-1 sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot "$@"' sh "$@" hotfixes_classic
}
fail() { echo "$*" >&2; exit 1; }
schemas=$(docker exec "$world" sh -c 'printf "%s\n%s\n%s\n" "$TC_REALM_ID" "${TC_WORLD_DATABASE_INFO##*;}" "${TC_HOTFIX_DATABASE_INFO##*;}"')
[[ $schemas == $'71\nworld_classic\nhotfixes_classic' ]] || fail "Expected isolated Classic realm 71"
[[ $(mysql_classic -N -e 'SELECT COUNT(*) FROM auth.realmlist WHERE id=71 AND port=8095 AND contentSetId=138') == 1 ]] || fail "Unexpected realm registration"
mysql_classic -t -e 'SELECT ID,Directory,ParentMapID,WdtFileDataID,Flags1,VerifiedBuild FROM map WHERE ID IN (0,9000); SELECT Id,UniqueId,RecordId,Status,VerifiedBuild FROM hotfix_data WHERE TableHash=3179597154 AND RecordId IN (0,9000);'
[[ $mode != check ]] || exit 0

if [[ $mode == apply ]]; then
    [[ $(mysql_classic -N -e 'SELECT COUNT(*) FROM map WHERE ID=9000 AND ParentMapID=0 AND WdtFileDataID=40011612 AND Flags1=2098688 AND VerifiedBuild=70790') == 1 ]] || fail "Apply the full-detail child candidate first"
    [[ $(mysql_classic -N -e 'SELECT COUNT(*) FROM world_classic.terrain_swap_defaults WHERE MapId=0 AND TerrainSwapMap=9000') == 1 ]] || fail "Expected active Classic terrain"
    [[ $(mysql_classic -N -e 'SELECT (SELECT COUNT(*) FROM map WHERE ID=0)+(SELECT COUNT(*) FROM hotfix_data WHERE TableHash=3179597154 AND RecordId=0)') == 0 ]] || fail "Map 0 already has hotfix data"
    change="
INSERT INTO map (ID,Directory,MapName,MapDescription0,MapDescription1,PvpShortDescription,PvpLongDescription,CorpseX,CorpseY,MapType,InstanceType,ExpansionID,AreaTableID,LoadingScreenID,TimeOfDayOverride,ParentMapID,CosmeticParentMapID,TimeOffset,MinimapIconScale,CorpseMapID,MaxPlayers,WindSettingsID,ZmpFileDataID,WdtFileDataID,OceanLiquidTypeID,NavigationMaxDistance,PreloadFileDataID,Flags1,Flags2,Flags3,VerifiedBuild)
VALUES (0,'Azeroth','Eastern Kingdoms','','','','',0,0,1,0,0,0,4,-1,-1,-1,0,1,-1,0,136,804940,775971,1250,0,0,161496669,135528464,2277510,70790);
INSERT INTO hotfix_data (Id,UniqueId,TableHash,RecordId,Status,VerifiedBuild)
VALUES (@push,@unique,3179597154,0,1,70790);"
else
    [[ $(mysql_classic -N -e "SELECT COUNT(*) FROM map WHERE ID=0 AND Directory='Azeroth' AND WdtFileDataID=775971 AND Flags1=161496669 AND VerifiedBuild=70790") == 1 ]] || fail "Expected the root terrain diagnostic row"
    [[ $(mysql_classic -N -e 'SELECT COUNT(*) FROM hotfix_data WHERE TableHash=3179597154 AND RecordId=0 AND Status=1 AND VerifiedBuild=70790') == 1 ]] || fail "Expected one active root diagnostic revision"
    # Send the original row at a fresh revision to supersede the cached override.
    change="
UPDATE map SET Flags1=159399517 WHERE ID=0 AND Flags1=161496669 AND VerifiedBuild=70790;
UPDATE hotfix_data SET Id=@push,UniqueId=@unique WHERE TableHash=3179597154 AND RecordId=0 AND Status=1 AND VerifiedBuild=70790;"
fi

docker stop --time 120 "$world" >/dev/null
trap 'docker start "$world" >/dev/null' EXIT
mysql_classic <<SQL
SET SESSION sql_mode='STRICT_ALL_TABLES';
START TRANSACTION;
SELECT MAX(Id)+1,MAX(UniqueId)+1 INTO @push,@unique FROM hotfix_data;
$change
COMMIT;
SQL
printf '%s complete. Classic is restarting.\n' "$mode"
