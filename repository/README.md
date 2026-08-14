# Engulf Package Repository

The workspace includes an optional HTTPS Python package repository and documentation
website. `repository.sh` builds a local image, starts one managed container, adds the
repository to the invoking user's pip configuration, and records enough state to
undo the launcher-owned host changes later.

This service is for a trusted Linux Docker host. It is separate from the Engulf
runtime and is not installed by any of the five Python distributions.

## Host Requirements

The launcher requires:

- Docker Engine available to the current user;
- OpenSSL, curl, `flock`, `getent`, `sudo`, and Python 3;
- TCP port 443 on the selected bind address;
- an existing server certificate and matching unencrypted private key;
- at least one DNS Subject Alternative Name (SAN) covered by the selected hostname.

The certificate must be within its validity period. A certificate with one concrete
DNS SAN selects that name automatically. Multiple concrete DNS SANs, or a
wildcard-only certificate, require `--hostname`; a wildcard covers exactly one DNS
label. IPv4 SANs are reported for remote-client use but do not select the canonical
hostname.

## Start The Service

For a certificate issued by a private CA, provide the CA certificate used to verify
the server certificate:

```console
./repository.sh start \
  --cert /path/to/server-certificate.pem \
  --key /path/to/server-private-key.pem \
  --ca-cert /path/to/issuing-ca-certificate.pem
```

Omit `--ca-cert` only when the server certificate is directly self-signed or its
chain is already trusted by the host. The launcher serves the server certificate
followed by the supplied CA material and builds a client bundle from the system
trust bundle plus that CA. It verifies certificate dates, the certificate/private-key
pair, hostname coverage, and the supplied CA chain before changing host state.

All `start` options are:

| Option | Meaning |
| --- | --- |
| `--cert PATH` | Required server certificate. |
| `--key PATH` | Required matching private key. |
| `--ca-cert PATH` | CA material that verifies the server certificate. |
| `--hostname FQDN` | Concrete DNS SAN to use when selection is ambiguous or wildcard-based. |
| `--storage DIRECTORY` | Existing persistent directory for uploaded artifacts. |
| `--public` | Bind port 443 on every IPv4 interface instead of loopback only. |

The default package storage is `.pypi-repository/packages/`. A custom storage
directory must already exist and be readable, writable, and searchable by the
launcher user. This deliberate check catches absent mounts and misspelled paths;
the launcher never creates a custom storage directory.

The default bind is `127.0.0.1:443`. `--public` changes it to `0.0.0.0:443` so remote
clients can connect. The launcher adds the selected FQDN to `/etc/hosts` only when
it does not already resolve over IPv4, and only on the local host. Remote clients
need working DNS, their own hosts entry, or a certificate IPv4 SAN.

After a health check succeeds, the launcher prints the repository, simple-index,
documentation, storage, and upload URLs.

## Routes And Authentication

| Route | Purpose | Authentication |
| --- | --- | --- |
| `/` | Browser landing page | Anonymous |
| `/simple/` | PEP 503-style package index used by pip | Anonymous |
| `/packages/` | Distribution artifact downloads | Anonymous |
| `/docs/` | Multi-page workspace and package documentation | Anonymous |
| `/docs/packages/` | Catalog generated from uploaded artifact metadata | Anonymous |
| `/health` | Container health probe | Anonymous |
| `POST /` | Twine package upload | Generated token |

The upload credential is a generated 256-bit token stored with mode 0600 in
`.pypi-repository/upload-token`. Its bcrypt verifier is mounted into the container;
the token itself is not. Downloads and documentation are intentionally unauthenticated,
so public mode must be used only on a network where that exposure is acceptable.

The container runs as the invoking user's numeric UID and GID. Docker owns the port
publication and associated firewall rules. TLS protects traffic, but the service is
not a package-signing or publisher-trust system.

## Configure Clients

The launcher adds its `/simple/` URL to the invoking user's pip
`global.extra-index-url` without replacing existing entries. If the certificate is
not already trusted, it also sets `global.cert` to a managed bundle while preserving
the previous value for cleanup.

`PIP_CONFIG_FILE`, `PIP_EXTRA_INDEX_URL`, and `PIP_CERT` can override those settings;
the launcher warns when they are present. Pip searches all configured indexes
without priority guarantees, so never reuse a private distribution name on an
untrusted public index.

A remote client can use the canonical hostname:

```console
PIP_CERT=/path/to/trusted-ca.pem \
python -m pip install --index-url https://packages.example.com/simple/ engulf
```

When the certificate contains a suitable IPv4 SAN, that address can be used
directly. `PIP_CERT` is unnecessary once the certificate chain is trusted. Pip
versions whose trust-store integration rejects literal IP addresses can use
`--use-deprecated=legacy-certs`; hostname-based access is unaffected.

## Publish Packages

Build and upload all five distributions to the URL printed by `start`:

```console
export TWINE_REPOSITORY_URL=https://packages.example.com/
./publish.sh
```

When the normalized URL exactly matches the active managed repository,
`publish.sh` verifies that the owned container is running and supplies Twine with
the stored token and managed CA bundle. It never prints the token. Any other URL
uses Twine's normal credential and certificate configuration.

Every successful file upload refreshes the uploaded-package catalog. Existing
artifacts are also scanned at container startup.

## Documentation Generation

The image builds `/docs/` with MkDocs in strict mode from the workspace overview,
the five package READMEs, the example READMEs, and this operator guide. Broken
internal links therefore fail the image build.

`/docs/packages/` is generated independently from metadata embedded in wheels and
source distributions. The scanner does not install, import, or extract package
code. It reads bounded `METADATA` or `PKG-INFO` records and publishes names,
versions, summaries, Python requirements, dependencies, project links, and artifact
downloads. The detail page uses metadata from the most recently modified artifact
for its description and dependency fields while listing every discovered version
and artifact.

Markdown descriptions are rendered and sanitized. Script tags, unsafe URL schemes,
and unsupported HTML attributes are removed; text contained by stripped tags remains
visible as text. Unknown description formats remain escaped plain text. Artifact
metadata is informative and is not a trust attestation.

## Inspect, Stop, And Recover

```console
./repository.sh status
./repository.sh logs
./repository.sh destroy
```

`status` reports container health, URL, and storage. `logs` shows Docker's current
log output for the managed container. `destroy` force-removes only the owned
container and reverses only the hosts and pip settings recorded by the launcher.
It does not delete package artifacts, generated credentials, copied certificates,
or other persistent `.pypi-repository/` data.

If somebody removes the container directly, the next launcher invocation detects
the stale active marker and reconciles the launcher-owned pip and hosts changes.
An existing container with the managed name but without the ownership label is
never modified. Concurrent launcher commands serialize through
`.pypi-repository/launcher.lock`.

Run the repository unit and shell-syntax checks with:

```console
make test-repository
```
