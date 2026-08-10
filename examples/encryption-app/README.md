# Encryption Goal Example

This example demonstrates an Engulf application whose goal performs its work in
Python rather than wrapping an executable. It uses `cryptography.fernet` for
authenticated encryption and exposes three modes within one encryption goal. It is
also the cross-platform reference application for running Engulf without the
Linux-specific executable-wrapper goal.

```console
engulf-encrypt generate-key secret.key
engulf-encrypt encrypt --key secret.key plaintext.txt ciphertext.bin
engulf-encrypt decrypt --key secret.key ciphertext.bin restored.txt
```

`EncryptionGoal` declares its own goal ID, API major, result type, and
`EncryptionPlugin` adapter type. It still receives Engulf diagnostics, context,
state, transactions, leases, and plugin phase dispatch through `GoalAPI`; it simply
does not need all of those facilities for this small example.
