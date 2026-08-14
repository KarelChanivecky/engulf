# Engulf Workspace

Engulf is a goal-oriented framework for managed, plugin-based CLI applications.
The core framework owns discovery, lifecycle, diagnostics, state, transactions, and
resource leases. Application-specific behavior lives in a **goal**.

This workspace contains five independently publishable Python 3.14 distributions:

| Directory | Distribution | Responsibility |
| --- | --- | --- |
| `engulf-api/` | `engulf-api` | Stable goal, plugin, lifecycle, and state contracts |
| `engulf/` | `engulf` | Application runtime, discovery, diagnostics, and state implementation |
| `engulf-executable-wrapper-api/` | `engulf-executable-wrapper-api` | Plugin contract for executable wrapping |
| `engulf-executable-wrapper/` | `engulf-executable-wrapper` | Executable goal, process runner, help, and completion |
| `plugins/engulf-plugin-list/` | `engulf-plugin-list` | Isolated executable-wrapper plugin inventory diagnostic |

## Documentation Map

The documentation website renders these files directly, so each package README is
both its package description and its authoritative developer guide. Start with the
page that owns the contract you are using:

| Task | Documentation |
| --- | --- |
| Define, brand, select plugins for, or invoke an application | [`engulf`](engulf/README.md) |
| Implement a goal or a goal-specific plugin API | [`engulf-api`](engulf-api/README.md) |
| Write an executable-wrapper plugin | [`engulf-executable-wrapper-api`](engulf-executable-wrapper-api/README.md) |
| Run a wrapped executable or install shell completion | [`engulf-executable-wrapper`](engulf-executable-wrapper/README.md) |
| Publish a sandboxed diagnostic extension | [Isolated diagnostic extensions](engulf/README.md#authoring-a-diagnostic-extension) |
| Learn application editions from a complete Python-only goal | [Encryption example](examples/encryption-app/README.md) |
| Operate the HTTPS package and documentation service | [Package repository](repository/README.md) |

Import public contracts from the package top levels (`engulf_api`, `engulf`, and
`engulf_executable_wrapper_api`). Underscore-prefixed modules and objects are
implementation details. The API distributions expose independent major-version
constants, while entry-point groups encode the relevant framework and goal majors.
The packages are still alpha even where an API contract is already versioned as 1.

`engulf` is not itself a binary wrapper. Wrapping an executable is one possible
goal, implemented by `ExecutableWrapperGoal`. A goal can instead implement all of
its work in Python, as shown by the reusable
[`examples/encryption-core`](examples/encryption-core/README.md) package and its thin
[`examples/encryption-app`](examples/encryption-app/README.md) launcher.

`engulf-api`, `engulf`, and goal API contracts are OS-independent. The core state
runtime selects a POSIX or Windows security and locking backend. The executable
wrapper runtime remains Linux-specific because its process-group, signal-forwarding,
and Bash/Zsh completion behavior is part of that goal.

## Installing Published Packages

Install the five published distributions from the indexes configured for pip:

```console
make install
```

Set `INSTALL_PYTHON` when the target interpreter is not named `python3.14`, for
example `make install INSTALL_PYTHON=.venv/bin/python`. This is the supported
consumer installation path. The editable commands below are only for development
inside a source checkout.

## Execution Boundaries

Engulf imports and executes every selected normal goal plugin in the application
process with that process's full operating-system authority. `PluginPolicy` is an
activation policy, `ElevationRequirement` is a compatibility declaration, and
managed state paths are namespace conveniences; none of them is a trust boundary or
sandbox. An elevated application therefore elevates every selected plugin.

Applications must select only trusted code when they run elevated. Keep application
code, its Python environment, and `plugin_dir` outside locations writable by less
privileged users. A future execution backend may isolate compatible plugins, so the
public contract exposes immutable plugin metadata and source records and routes
callbacks through stable phase IDs. No current plugin should infer that isolation is
already present.

Diagnostic extensions are a separate, automatically discovered extension kind.
Their targets are never imported by the application process. On Linux, an exact
reserved trigger runs each matching target in its own bounded Bubblewrap sandbox,
using a length-limited JSON protocol. The sandbox has no workspace, home, host
temporary directory, or network view. If that isolation cannot be established,
Engulf leaves diagnostics disabled and safely rejects their declared triggers.
This boundary does not make normal goal plugins safer: those remain trusted,
in-process code with the application's full authority.

## Source Development

Create a Python 3.14 environment. Use that environment's interpreter for the
remaining commands: `.venv/bin/python` on POSIX or
`.venv\Scripts\python.exe` on Windows.

```console
python -m venv --upgrade-deps .venv
python -m pip install --group dev
python -m pip install --no-deps -e ./engulf-api -e ./engulf -e ./engulf-executable-wrapper-api -e ./engulf-executable-wrapper -e ./plugins/engulf-plugin-list -e ./examples/encryption-core -e ./examples/encryption-app
```

Run every suite from the workspace root:

```console
python -m unittest discover -s engulf-api/tests -v
python -m unittest discover -s engulf-executable-wrapper-api/tests -v
python -m unittest discover -s engulf/tests -v
# Linux only:
python -m unittest discover -s engulf-executable-wrapper/tests -v
python -m ruff check engulf-api engulf engulf-executable-wrapper-api engulf-executable-wrapper plugins examples
python -m ruff format --check engulf-api engulf engulf-executable-wrapper-api engulf-executable-wrapper plugins examples
python -m mypy
```

Build all five wheels and source distributions, then validate their package
metadata with Twine. The script creates `.venv` and installs the development
dependencies when the workspace environment does not exist:

```console
./build.sh
```

## Publishing

Set an explicit PyPI-compatible upload URL and publish all five distributions.
Twine reads credentials from its standard configuration or the `TWINE_USERNAME` and
`TWINE_PASSWORD` environment variables:

```console
export TWINE_REPOSITORY_URL=https://test.pypi.org/legacy/
./publish.sh
```

Use the production upload endpoint for real PyPI:

```console
export TWINE_REPOSITORY_URL=https://upload.pypi.org/legacy/
./publish.sh
```

`build.sh` and `publish.sh` are convenience wrappers around the corresponding
Makefile targets. Builds use a clean root `dist/` directory so old artifacts are
not uploaded accidentally.

## Local Package Repository

The complete flag, certificate, storage, security, endpoint, and recovery reference
is in [`repository/README.md`](repository/README.md). The common workflow follows.

On a Linux Docker host with Docker Engine, OpenSSL, curl, `flock`, `getent`, `sudo`,
and Python 3 available, launch a persistent HTTPS package repository using a
certificate and matching private key:

```console
./repository.sh start \
  --cert /path/to/server-certificate.pem \
  --key /path/to/server-private-key.pem \
  --ca-cert /path/to/issuing-ca-certificate.pem
```

The launcher reads the canonical hostname from the certificate's DNS Subject
Alternative Name (SAN). If the certificate contains multiple DNS names or only a
wildcard, select one concrete covered name with `--hostname`. IPv4 SANs do not make
the DNS choice ambiguous. The launcher validates the certificate dates and key
before changing the host.

For a certificate signed by a private CA, pass the CA certificate with `--ca-cert`.
The launcher serves it as part of the TLS chain and adds the CA—not the server leaf
certificate—to pip's managed trust bundle. Omit `--ca-cert` only when the server
certificate is directly self-signed or its chain is already trusted by the system.

Package artifacts use `.pypi-repository/packages/` by default. To store them on an
already-mounted filesystem or another persistent host directory, pass its existing
path with `--storage`:

```console
./repository.sh start \
  --cert /path/to/server-certificate.pem \
  --key /path/to/server-private-key.pem \
  --ca-cert /path/to/issuing-ca-certificate.pem \
  --storage /mnt/package-repository
```

The launcher deliberately does not create a custom storage directory, which catches
misspelled or absent paths. The directory must be readable, writable, and searchable
by the user running the launcher. Administrators remain responsible for ensuring a
network or removable filesystem is mounted before launch. Destroying the container
never removes package artifacts from either the default or custom storage directory.

Private mode binds HTTPS only to `127.0.0.1:443`. To make downloads reachable from
the network, use:

```console
./repository.sh start \
  --cert /path/to/server-certificate.pem \
  --key /path/to/server-private-key.pem \
  --ca-cert /path/to/issuing-ca-certificate.pem \
  --public
```

Public mode publishes Docker port 443 on all IPv4 interfaces. Docker owns and
removes the associated firewall rules with the container. Downloads and package
listing are anonymous; uploads require a generated 256-bit token. Remote clients
can use working DNS or a certificate IPv4 SAN directly, and must trust the supplied
certificate chain. The launcher modifies only the local host's `/etc/hosts`, mapping
the selected FQDN to `127.0.0.1` when it does not already resolve.

For example, a remote client can use an IPv4 SAN without a hosts entry:

```console
PIP_CERT=/path/to/trusted-ca-or-certificate.pem \
python -m pip install --index-url https://192.0.2.10/simple/ engulf
```

`PIP_CERT` is unnecessary when the certificate is already trusted. Pip versions
whose trust-store integration rejects a literal IP can use
`--use-deprecated=legacy-certs` until that client issue is resolved; hostname-based
access is unaffected.

The repository is added to the invoking user's pip `extra-index-url` list without
replacing existing indexes. If necessary, pip is also pointed at a managed CA bundle.
Environment variables such as `PIP_CONFIG_FILE`, `PIP_EXTRA_INDEX_URL`, and
`PIP_CERT` take precedence over this configuration. Pip does not prioritize one
configured index over another, so do not reuse private distribution names on an
untrusted public index.

The repository landing page links to rendered documentation at `/docs/`. The
documentation site is built into the container from the root overview, all five
package READMEs, the example application READMEs, and the repository operator guide.
Pip continues to use
`/simple/`, independently of the browser-facing documentation routes.

Every successful package upload also refreshes the uploaded package catalog at
`/docs/packages/`. The generated catalog reads wheel or source-distribution metadata
without installing or importing uploaded code and exposes package descriptions,
versions, dependencies, Python requirements, project links, and distribution files.
Existing packages are scanned when the container starts. Every generated package
page links back to the multi-page Engulf documentation; declared project URLs are
also shown because standard distribution metadata contains only one long
description.

Descriptions declared as `text/markdown` are rendered with headings, lists, tables,
links, and fenced code blocks. Generated HTML is sanitized before publication;
unknown description formats remain escaped plain text.

Publish to the running repository by using the URL printed by the launcher:

```console
export TWINE_REPOSITORY_URL=https://packages.example.com/
./publish.sh
```

For that exact managed URL, `publish.sh` loads the generated upload credential and
CA bundle without printing the token. Other URLs use normal Twine authentication.

Inspect or remove the service with:

```console
./repository.sh status
./repository.sh logs
./repository.sh destroy
```

`destroy` removes the container and only the hosts/pip settings created by the
launcher. Packages and the upload credential remain in the ignored
`.pypi-repository/` directory. If the container is removed directly with Docker,
the next launcher invocation reconciles stale hosts and pip configuration.

See [`engulf/README.md`](engulf/README.md) for application and discovery behavior,
and [`engulf-executable-wrapper-api/README.md`](engulf-executable-wrapper-api/README.md)
for complete executable-wrapper plugin packaging instructions.
