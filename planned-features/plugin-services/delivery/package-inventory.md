# Source package inventory

Back to [delivery](README.md). Refreshed after the v4 critique: 45 project-bearing
`pyproject.toml` files, 7 in Engulf and 38 in engulf-clab. Heads are `4c7e95e` and
`f8c9063`; observations can expire on the next source change. No release versions
are reserved and no package metadata or index was changed by this inventory.

The beta reset supersedes the old versions. The former sleep consumer is now
`engulf-clab-reclaim` (rename commit `e543a30`), with plugin ID `engulf_clab.reclaim`
and lease `eclab-reclaim:docker`. Keep the historical design page path and R-SLEEP
gate label for navigation; implementation uses the current names.

| Repository | Distribution | Observed version | A action |
| --- | --- | --- | --- |
| engulf | engulf-api | 1.0.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf | engulf-executable-wrapper-api | 1.0.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf | engulf-executable-wrapper | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf | engulf | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf | engulf-encryption-example | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf | engulf-encryption-example-core | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf | engulf-plugin-list | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-demo-lab | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-mcp | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-all-plugins | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-consumption | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-containers-api | 1.0.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-containers-core | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-containers-pki | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-containers | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-develop-eclab-lab | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-dockerfile-build | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-ensure-checkout | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-ensure-containerlab | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-ensure-vrnetlab | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-freeze-api | 1.0.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-freeze | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-image-archive | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-image-build | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-lab-parser | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-lab-registry-api | 1.0.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-lab-registry | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-lab-writer | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-license-pool | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-pki-api | 1.0.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-pki-linux-core | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-pki-linux-debian | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-pki-linux-fedora | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-pki | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-reclaim | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-schema-api | 1.0.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-schema | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-sticky-ip | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-vrnetlab-build | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-vrnetlab-fortigate-pki-injector | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-wan | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-docker-image-api | 1.0.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-docker-image-core | 1.0.0 | Select release/floor from refreshed manifest when releasing; no current bump |
| engulf-clab | engulf-clab-develop-eclab-lab-static | 0.1.0 | Select release/floor from refreshed manifest when releasing; no current bump |

## Machine-readable evidence

[package-inventory.json](package-inventory.json) records paths, direct dependencies,
extras, entry points, source hashes and heads. It is an observation, not a lock file.
[review-source-snapshot.json](review-source-snapshot.json) captures the source used
for reassessment. The original [source snapshot](source-snapshot.json) remains
historical evidence and is not an implementation/release input.

At A3/B8, refresh both inventories and add explicitly owned downstream roots. Check
that versions, hashes and catalog groups match the built wheels; then run resolver,
`pip check`, application smoke tests and the separate plugin-packaging diagnostic.
The two-repository inventory cannot enumerate externally owned consumers.
