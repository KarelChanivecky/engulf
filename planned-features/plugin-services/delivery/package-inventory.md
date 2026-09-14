# Source package inventory

Back to [delivery](README.md). Snapshot of 45 project-bearing `pyproject.toml` files:
7 in Engulf (five public packages plus two examples), 38 in the sibling checkout.
This records source versions, not package-index availability. The sibling is being
edited concurrently; refresh this manifest before any release.

| Repository | Distribution | Observed version | A action |
| --- | --- | --- | --- |
| engulf | engulf-api | 1.3.0 | 1.4.0 candidate; core API definitions |
| engulf | engulf-executable-wrapper-api | 1.2.1 | 1.3.0 candidate; support definitions |
| engulf | engulf-executable-wrapper | 0.3.0 | 0.4.0 candidate; unavailable support |
| engulf | engulf | 0.3.0 | 0.4.0 candidate; unavailable runtime |
| engulf | engulf-encryption-example | 0.1.0 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf | engulf-encryption-example-core | 0.1.0 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf | engulf-plugin-list | 0.1.1 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-demo-lab | 0.5.0 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab | 0.3.2 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-mcp | 0.1.5 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-all-plugins | 0.8.5 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-consumption | 0.2.0 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-containers-api | 1.2.1 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-containers-core | 0.3.2 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-containers-pki | 0.1.0 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-containers | 0.4.2 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-develop-eclab-lab | 0.2.1 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-dockerfile-build | 0.3.2 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-ensure-checkout | 0.2.0 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-ensure-containerlab | 0.3.1 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-ensure-vrnetlab | 0.2.2 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-freeze-api | 1.0.0 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-freeze | 0.4.1 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-image-archive | 0.3.2 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-image-build | 0.2.3 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-lab-parser | 0.2.2 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-lab-registry-api | 1.0.1 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-lab-registry | 0.1.1 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-lab-writer | 0.2.2 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-license-pool | 0.3.2 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-pki-api | 2.0.1 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-pki-linux-core | 0.1.2 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-pki-linux-debian | 0.1.2 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-pki-linux-fedora | 0.1.2 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-pki | 0.3.2 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-schema-api | 2.0.0 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-schema | 0.2.0 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-sleep | 0.1.1 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-sticky-ip | 0.1.0 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-vrnetlab-build | 0.4.2 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-vrnetlab-fortigate-pki-injector | 0.2.2 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-wan | 0.3.2 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-docker-image-api | 1.4.1 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-docker-image-core | 1.4.0 | Next unused patch for coordinated metadata; raise applicable direct floors |
| engulf-clab | engulf-clab-develop-eclab-lab-static | 0.1.3 | Next unused patch for coordinated metadata; raise applicable direct floors |

## Machine-readable evidence

[package-inventory.json](package-inventory.json) records paths, current dependencies,
extras, entry-point groups and SHA-256 hashes of the inspected metadata. It has no
proposed writes and is not an installation lock file. Compare catalog groups before
and after A; do not replace `engulf.plugins.v1` because a package version changes.

The rollout owner must classify publishable/example/internal packages and add any
explicitly owned downstream roots before marking an ecosystem release complete.
The two-repository inventory is complete for the paths returned by `rg --files` at
capture time; it does not discover repositories elsewhere on the machine or query
a package index.
