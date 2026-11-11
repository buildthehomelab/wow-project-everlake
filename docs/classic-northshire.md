# Northshire on the Roleplay test realm

Use the existing Roleplay test realm, ID 71 on port 8095. Its current login, ruleset card and `characters2` database carry over. The terrain swap and Human Warrior start change are installed in copies of `world` and `hotfixes2`.

Stage the combined server data in a separate directory on the host. Start from the matching core image's existing extracted data, then add the verified map 9000 terrain, collision models and navigation files. Set `CLASSIC_DATA_DIR` to that directory. The app mounts it read-only. The Mac test copy must have the corresponding combined client build with WDT FileDataID 40011612 and must use the existing hosted login.

From the pulled Everlake checkout on TrueNAS, run `sudo ./scripts/classic-setup.sh`. It connects directly to the running `ix-everlake-mysql-1` container and uses its configured database user. Classic's world tables live in `world_classic` on that server. The script checks the existing realm row and aborts if either target schema exists. If it stops during import, inspect the partial target schemas before retrying.

Apply the override to the existing Roleplay app. For a Compose deployment, use the existing app project name and combine the files in this order:

```sh
docker compose -f docker-compose.realm2-app.yml -f docker-compose.classic-terrain.yml up -d worldserver2
```

Check the existing Roleplay app's logs for map data and database startup errors. From the isolated Mac copy, select the Roleplay realm, create a Human Warrior and confirm it spawns in pre-Shattering Northshire. The staged terrain was built against client 70790. Confirm the hosted login accepts the installed test client's build before attempting the smoke test.

To roll back the terrain test, recreate the Roleplay worldserver with its original app configuration.
