# HueManager

HueManager is a local **selective Philips Hue migration tool** for moving chosen rooms from one Hue Bridge to another (including a Hue Bridge Pro) while preserving as much bridge-side configuration as possible.

It combines:

- Hue **CLIP v2** for rooms, devices and scenes;
- Hue **CLIP v1** for Zigbee `uniqueid` matching and bridge rules;
- dependency analysis for advanced configurations created by apps such as iConnectHue.

The source bridge is never deleted or cleaned automatically.

## Web interface

Python 3.11+:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
huemanager web
```

Open:

```text
http://127.0.0.1:8787
```

The web UI can:

- pair HueManager with a Bridge after you press its physical link button;
- discover Bridges through the official Hue discovery service;
- display a tree of **rooms → devices → scenes → CLIP rules → Hue v2 automations**;
- select one or several rooms;
- show cross-room dependencies before migration;
- create a durable pre-migration snapshot;
- start light or accessory search on the destination Bridge;
- verify that every physical resource has been found on the destination;
- recreate rooms, scenes, Hue v2 `behavior_instance` graphs, virtual CLIP sensors, rules and relevant resource-link metadata.

## iConnectHue / advanced switch configurations

A button configuration is not assumed to belong only to the room where the switch is located. HueManager analyses every referenced Hue resource in the matching bridge rules.

Example:

```text
Dimmer Bureau / button 1
  ├─ condition: /sensors/4/state/buttonevent
  ├─ action: Bureau /groups/3
  └─ action: Salon  /groups/9
```

If **Bureau + Salon** are selected, both group references are mapped and the two actions are retained.

If only **Bureau** is selected, HueManager raises an external-dependency warning and, by default, recreates the rule with only the Bureau action. The removed link is included in the final migration report.

The same pruning policy applies to out-of-scope conditions, but those are explicitly reported as a **semantic change**, because removing a condition can broaden when a rule triggers. A rule is skipped if pruning leaves it without any useful action or without any remaining condition when the original rule had conditions.

HueManager also follows and snapshots referenced **CLIP virtual sensors** (`CLIPGenericStatus`, `CLIPGenericFlag`, etc.), which advanced Hue configurations can use as bridge-local variables. They are recreated before dependent rules.

Relevant CLIP v1 `resourcelinks` are recreated after the rules. Resource links are client-side grouping metadata rather than executable automation logic. Their links are remapped to the resources recreated by HueManager; out-of-scope metadata links are pruned and reported.

## Safe workflow

### 1. Pair the two Bridges

From the web UI, press the physical Bridge button and use **Appairer**.

CLI equivalent:

```bash
huemanager pair old 192.168.1.20
huemanager pair pro 192.168.1.21
```

### 2. Create a snapshot before moving devices

Web: select one or more rooms and click **Créer le snapshot**.

CLI:

```bash
huemanager snapshot old -r "Bureau" -r "Salon" -o bureau-salon.json
```

The snapshot records selected devices, scenes, bridge rules, virtual CLIP dependencies, resource links and cross-room references.

### 3. Release selected devices from the source Bridge

The web workflow can now delete only the physical CLIP v2 devices contained in the persistent snapshot. Deletion is performed once per device (not once per service), and it is idempotent: retrying the step reports devices that are already absent instead of treating them as failures.

The snapshot and migration session are stored under the HueManager configuration directory, so closing the browser or restarting the container does not lose the migration state.

### 4. Pair/reset physical devices onto the destination Bridge

The web UI can start Bridge searches for lamps and accessories as many times as required. If automatic discovery is incomplete, power-cycle or reset the missing devices, then retry the search later.

CLI:

```bash
huemanager scan pro --kind lights
huemanager scan pro --kind sensors
```

### 5. Verify mapping

```bash
huemanager plan bureau-salon.json pro
```

Physical lights/sensors are matched by their Zigbee `uniqueid`. `ready: true` means all physical resources needed by the selection are present on the destination. A partial result is persisted in the web migration session and can be checked again later.

### 6. Restore

```bash
huemanager apply bureau-salon.json pro
huemanager apply bureau-salon.json pro --execute
```

The normal web restore remains blocked while required physical resources are missing because destination IDs do not exist yet.

The web UI also provides an explicit **forced partial restore** for devices that are permanently gone or cannot be re-associated. In that mode HueManager never invents destination IDs: unavailable scene actions are pruned, empty scenes are skipped, rules/behavior graphs are pruned or skipped when their missing references make them invalid, and schedules/Entertainment/resource links with unresolved targets are reported.

By default, out-of-scope rule links are pruned and reported. To use strict CLI behavior (skip a rule instead of pruning external references):

```bash
huemanager apply bureau-salon.json pro --execute --keep-external-strict
```

## What is preserved

Current v0.6 scope:

- selected rooms and device membership;
- Hue v2 scenes and scene actions;
- Hue v2 `behavior_instance` graphs, including nested UUID references and UUID-keyed button configurations;
- Hue v2 `entertainment_configuration` resources used by Hue Entertainment clients such as iLightShow/Hue Sync;
- `behavior_script` matching by ID or script metadata/version when required;
- physical light/sensor mapping by Zigbee `uniqueid`;
- CLIP virtual sensors used by selected rule graphs;
- CLIP v1 rules, including cross-room rules when all referenced rooms are selected;
- relevant CLIP v1 resource links;
- explicit warnings and pruning reports for references outside the selected perimeter.

## Current limitations

- A destination Bridge can reject a recreated `behavior_instance` if its installed behavior script/schema differs from the source. HueManager reports and skips that automation instead of aborting the whole migration.
- Generic v2 graph pruning is conservative: if removing an external reference empties a required branch (`where`, `what`, `actions`, `slots`, `items`), the branch or automation is dropped rather than broadened.
- Entertainment areas, Matter/HomeKit bindings and third-party cloud account configuration are not migrated.
- A Zigbee device still has to join the destination Bridge network before it can receive a real destination resource ID. The forced partial restore only skips/prunes resources tied to missing devices; it does not fabricate IDs or transfer Zigbee credentials.
- full-bridge restore recreates CLIP v1 schedules after rules; cyclic rule↔schedule dependencies or schedules referencing unsupported resources are skipped and reported rather than restored with stale IDs.
- Hue v2 `smart_scene` resources are preserved in the raw backup archive but are not recreated automatically yet.
- Recreating a third-party application's resource-link metadata does not guarantee that the third-party app will claim or display those resources as if it had created them itself.


## Docker / Synology NAS

The GitHub Actions workflow validates Python/lint/tests, builds the Python wheel, then publishes a multi-architecture image to GitHub Container Registry on pushes to `main` and version tags:

```text
ghcr.io/albaintor/huemanager
```

Published platforms:

- `linux/amd64`;
- `linux/arm64`.

Tags follow the same convention as the Pilot project:

- `main` → `latest` and `sha-<commit>`;
- Git tag `v0.4.0` → Docker tags `0.4.0`, `0.4`, `0`;
- pull requests run validation only and do not publish images;
- the workflow can also be launched manually from **Actions → CI → Run workflow**.

For a Synology NAS:

```bash
mkdir -p huemanager/config
cd huemanager
# copy docker-compose.yml and optionally .env.example -> .env
docker compose pull
docker compose up -d
```

Default URL:

```text
http://<NAS>:8787
```

Optional `.env`:

```ini
HUEMANAGER_IMAGE_TAG=latest
HUEMANAGER_PORT=8787
```

For a pinned release/rollback, set for example:

```ini
HUEMANAGER_IMAGE_TAG=0.4.0
```

The Compose mount is intentionally read/write:

```text
./config:/app/config
```

It persists:

```text
config/
├── config.json       # local Bridge API profiles/keys
├── snapshots/        # selective migration snapshots
└── backups/          # full bridge archive + logical restore files
```

Do not publish or commit this directory. It contains Hue API credentials in `config.json`. Backup files themselves redact `config.whitelist` API usernames.

If the GHCR package is private:

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u albaintor --password-stdin
```

The container includes an HTTP healthcheck on `/api/health`.

The HueManager web UI currently has no application-level HTTP authentication. Keep port
`8787` on the trusted LAN/VPN, or place it behind an authenticated reverse proxy. Do not
publish it directly to the Internet.

## Full bridge backup / restore

HueManager 0.4 adds a full backup workflow alongside selective room migration.

A backup contains two layers:

1. a **raw archive** of the CLIP v1 root and all CLIP v2 resources, with Hue API usernames redacted;
2. a **portable logical snapshot** used by HueManager to reconstruct supported configuration on a destination Bridge.

Web UI: use **Backup / restore du Bridge** at the bottom of the page. Backups can be downloaded as JSON and later re-imported from the same panel.

CLI:

```bash
huemanager backup old -o old-bridge.json
huemanager restore old-bridge.json pro
huemanager restore old-bridge.json pro --execute
```

`restore` is a dry-run unless `--execute` is supplied.

The logical restore currently covers:

- light/accessory names after matching physical resources by `uniqueid`;
- rooms and membership;
- zones and their mapped children;
- v2 scenes;
- v2 Hue Entertainment configurations;
- v2 `behavior_instance` automation graphs;
- virtual CLIP sensors;
- CLIP v1 rules;
- CLIP v1 schedules;
- resource links.

A full Hue Bridge firmware/network image is **not** possible through the public local API. HueManager cannot restore the Zigbee network key or silently move paired devices. Lights and accessories must first be paired/reset onto the target Bridge. The restore plan stays blocked until the required physical resources can be matched.

The raw archive is kept even for resource types HueManager does not currently recreate automatically, so a future HueManager version or manual recovery still has the source data.

## Development

```bash
pip install -e '.[dev]'
ruff check src tests
pytest -q
```


## Pairing identifiers

HueManager displays the identifiers that the Bridge actually exposes for each device:

- Zigbee MAC address from the v2 `zigbee_connectivity` resource;
- CLIP v1 `uniqueid` values;
- a serial/setup/pairing field if a future/particular resource really exposes one.

HueManager **does not derive a six-character Hue serial number from the Zigbee MAC or uniqueid**. The physical six-character serial and QR/setup code are not generally exposed by the Hue Bridge API, so presenting a derived value as a pairing code would be unsafe. The UI explicitly marks the serial/QR as unavailable when the Bridge did not return one.

The destination search buttons can initiate discovery for lights and accessories. Devices that are still commissioned to another Zigbee network may still require the normal reset, physical pairing procedure, QR/serial entry in Hue, or another supported commissioning method.


## iLightShow

iLightShow uses the Hue Bridge and automatically manages Hue Entertainment groups from the
lights selected in the app. HueManager now snapshots and recreates matching
`entertainment_configuration` resources and remaps their entertainment services to the
destination lights.

This does **not** migrate iLightShow's own application credentials, presets or per-light
settings stored by iLightShow itself. After a selective move to another Bridge, reconnect
iLightShow to that Bridge with its Link button flow and verify/reselect its lights. iLightShow
can then reuse or recreate its Entertainment configuration as needed.

HueManager does not invoke Philips' proprietary Bridge-to-Bridge migration service. Physical
Hue devices still have to join the destination Zigbee network before the logical restore can
complete.

## Gestion et audit du Bridge

L'onglet **Gestion** analyse un Bridge sans le modifier et détecte notamment les pièces vides,
les règles sans action, les références v1/v2 cassées, les scènes vides/orphelines, les schedules
et resource links incohérents ainsi que les automations v2 qui ciblent des ressources absentes.

Chaque anomalie indique si le nettoyage est considéré à faible risque ou s'il nécessite une
confirmation explicite. Pour les suppressions risquées, HueManager explique la raison : ressource
encore référencée, règle partiellement valide, automation comportant encore des branches utiles,
métadonnées potentiellement détenues par une application tierce, etc.

Plusieurs éléments peuvent être sélectionnés en même temps, avec **Tout sélectionner** et
**Tout désélectionner**, puis supprimés en une seule opération. Avant chaque suppression du lot,
HueManager relance l'audit : si une anomalie a disparu ou changé à la suite d'un nettoyage précédent,
elle est ignorée plutôt que supprimée sur la base d'un état devenu obsolète.



## Apple Maison : synchronisation des pièces Hue

HueManager 0.7 ajoute un planificateur de correspondance entre les pièces du Bridge Hue et les
pièces Apple Maison.

L'affectation d'un accessoire à une pièce Apple est stockée dans la base HomeKit du compte Apple,
pas dans le Bridge Hue. Le serveur HueManager calcule donc les correspondances et les actions,
tandis que l'application compagnon `apple-home-helper`, autorisée HomeKit sur macOS, lit et
modifie la base Maison.

Le matching des pièces est volontairement heuristique mais conservateur :

- égalité après normalisation des accents, espaces et casse ;
- synonymes français/anglais comme Salon/Séjour/Living room, Bureau/Office,
  Salle de bain/SDB/Bathroom, Entrée/Hallway ;
- noms partiels comme `Chambre Louis` et `Louis` ;
- score de similarité avec détection des ambiguïtés ;
- correspondance manuelle persistante disponible depuis l'onglet Gestion.

Les accessoires sont appariés en priorité avec les identifiants disponibles (numéro de série/MAC
lorsqu'ils correspondent), puis par nom normalisé et enfin par similarité de nom avec seuil élevé.

Le compagnon macOS dispose aussi d'un mode **Synchronisation automatique sûre**. Après
l'autorisation HomeKit initiale, il peut republier l'inventaire et appliquer périodiquement les
déplacements sans intervention. Le mode auto s'arrête et ne modifie rien si une pièce ou un
accessoire est ambigu, absent, ou si le score heuristique est inférieur aux seuils de confiance.

Un contrôleur HAP/HomeKit tiers exécuté dans Docker ne peut pas remplacer ce compagnon pour cette
fonction : les pièces Apple appartiennent à la base HomeKit du contrôleur Apple et ne sont pas
des propriétés stockées dans les accessoires Hue.
