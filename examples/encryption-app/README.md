# Encryption Goal Example

This thin launcher depends on `engulf-encryption-example-core`, whose goal performs
its work in Python rather than wrapping an executable. The core package exports a
side-effect-free `ENCRYPTION_APPLICATION` definition; this package only creates a
fresh application and provides the official console command.

```console
engulf-encrypt generate-key secret.key
engulf-encrypt encrypt --key secret.key plaintext.txt ciphertext.bin
engulf-encrypt decrypt --key secret.key ciphertext.bin restored.txt
```

`EncryptionGoal` declares its own goal ID, API major, result type, and
`EncryptionPlugin` adapter type. It obtains its command-facing name from
`GoalSetupAPI.display_name`, so a vendor can derive an edition under another command
name without changing the goal.

A vendor launcher can depend on the core package and derive an edition:

```python
from engulf_encryption_example_core import ENCRYPTION_APPLICATION

VENDOR_APPLICATION = ENCRYPTION_APPLICATION.edition(
    display_name="vendor-encrypt",
    vendor="Vendor Corp",
    product="Vendor Encrypt",
    version="0.1.0-vendor.1",
    require_plugins={"com.vendor.encryption-policy"},
)


def main() -> int:
    with VENDOR_APPLICATION.create() as application:
        return application.run()
```

The edition retains the encryption application's identity, declarations, state, and
leases. A vendor needing an independent product uses `fork()` instead.
