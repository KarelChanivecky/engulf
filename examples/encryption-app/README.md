# Encryption Goal Example

This thin launcher depends on `engulf-encryption-example-core`, whose goal performs
its work in Python rather than wrapping an executable. The core package exports a
side-effect-free `ENCRYPTION_APPLICATION` definition; this package only creates a
fresh application and provides the official console command.

The launcher module exports `ENCRYPTION_APPLICATION` and `main`. `main()` creates the
application in a context manager, delegates `sys.argv[1:]` to `Application.run()`,
and closes runtime plugin endpoints during exit. Importing the launcher does not
discover plugins or run goal setup.

Install both example packages from a source checkout with the editable-development
command in the [workspace overview](../../README.md#source-development), or install
the published `engulf-encryption-example` distribution and its dependencies.

```console
engulf-encrypt generate-key secret.key
engulf-encrypt encrypt --key secret.key plaintext.txt ciphertext.bin
engulf-encrypt decrypt --key secret.key ciphertext.bin restored.txt
```

Successful commands exit 0. The goal intentionally has no installed privilege
opt-in, so running the launcher elevated reports `GoalPrivilegeError` on stderr and
exits 70 before plugins or goal setup run. Invalid command syntax is a rejected goal result with
exit 2. Missing files, invalid keys/tokens, permissions, and other file or
cryptography errors are failed goal results with exit 1. Framework, plugin, or
cleanup failures use exit 70. The output path is replaced when writable; key and
plaintext handling in this example is intentionally minimal.

`EncryptionGoal` declares its own goal ID, API major, result type, and
`EncryptionPlugin` adapter type. It obtains its command-facing name from
`GoalSetupAPI.display_name`, so a vendor can derive an edition under another command
name without changing the goal.

A vendor launcher can depend on the core package and derive an edition:

```python
import sys

from engulf import FRAMEWORK_ERROR_EXIT, GoalPrivilegeError
from engulf_encryption_example_core import ENCRYPTION_APPLICATION

VENDOR_APPLICATION = ENCRYPTION_APPLICATION.edition(
    display_name="vendor-encrypt",
    vendor="Vendor Corp",
    product="Vendor Encrypt",
    short_product_name="VEncrypt",
    version="0.1.1-vendor.1",
    require_plugins={"com.vendor.encryption-policy"},
)


def main() -> int:
    try:
        with VENDOR_APPLICATION.create() as application:
            return application.run()
    except GoalPrivilegeError as error:
        print(f"vendor-encrypt: {error}", file=sys.stderr)
        return FRAMEWORK_ERROR_EXIT
```

The edition retains the encryption application's identity, declarations, state, and
leases. A vendor needing an independent product uses `fork()` instead.

The vendor launcher wheel should expose only its own console script and depend on
`engulf-encryption-example-core`, not on the official launcher distribution. Its
required plugin wheels should also be normal Python dependencies so installation
and Engulf activation policy agree. The vendor-only plugin publishes the encryption
goal catalog entry but should omit the shared application declaration unless the
official launcher is also meant to activate it.

This example's goal contract is co-located with the application core for brevity.
See [`engulf-api`](../../engulf-api/README.md#goal-contract) for the production pattern
in which a reusable third-party plugin ecosystem gets a separate dependency-light
goal API distribution.
