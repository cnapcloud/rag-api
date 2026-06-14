# SIGILL / SIGKILL on K8s — Mac Multipass QEMU

## Symptom

Running `ingest_job` on a K8s cluster causes the process to terminate with a signal
at two distinct points:

1. **SIGILL (signal 4)** — `embed_op`, during sparse embedding initialization:
   ```
   ENGINE_EVENT: Run execution process was terminated by signal 4 (SIGILL).
   ```
   Call path:
   ```
   embed_op
     └─ embed()
          └─ build_sparse_model()
               └─ fastembed.SparseTextEmbedding("Qdrant/bm25")
                    └─ onnxruntime  ← SIGILL (QEMU ARM64)
   ```

2. **SIGKILL (signal 9)** — `parse_op`, during document loading:
   ```
   ENGINE_EVENT: Run execution process was terminated by signal 9 (SIGKILL).
   ```
   Call path:
   ```
   parse_op
     └─ LlamaIndex document loader (internal library)
          └─ ← SIGKILL (QEMU ARM64, separate root cause)
   ```

Both signals occur on K8s nodes running on QEMU. The same image works normally under
Docker Desktop on Mac.

## Scope

Confirmed on **Mac (Apple Silicon) with Multipass QEMU** only.
This is not an ARM64 Linux issue — it is specific to the Mac + Multipass QEMU combination
where the CPU is exposed as `part: 0x000` (unidentified) to the guest VM.
Native ARM64 Linux hosts are unaffected by this root cause.

## Environment

| Item | Value |
|------|-------|
| Host | Apple Silicon Mac |
| K8s node OS | Ubuntu 22.04 on Apple Silicon (Multipass QEMU) |
| Container architecture | ARM64 |
| Virtualization | Multipass QEMU backend |
| CPU info | implementer: 0x61 (Apple), part: 0x000 (unidentified) |

## Root Cause

### SIGILL — onnxruntime NEON detection failure

`fastembed` uses `onnxruntime` internally to generate BM25 sparse vectors.
`onnxruntime` detects ARM CPU features at runtime and selects a NEON SIMD code path.
Under Multipass QEMU, the CPU is reported as `part: 0x000` (unidentified), causing
CPU feature detection to fail. `onnxruntime` then attempts to execute an unsupported
instruction, triggering SIGILL.

```
onnxruntime cpuid_info warning: Unknown CPU vendor. cpuinfo_vendor value: 0
```

### SIGKILL — LlamaIndex document loader

The document loader used inside `parse_op` triggers SIGKILL on QEMU ARM64.
This is a separate root cause from the SIGILL above and is not resolved by fixing
the onnxruntime issue alone.

### Docker Desktop vs K8s difference

- **Docker Desktop (Mac)**: macOS Hypervisor.framework fully exposes Apple Silicon CPU
  features to the Linux VM — onnxruntime works correctly.
- **Multipass QEMU**: CPU reported as `part: 0x000` — both onnxruntime detection failure
  and document loader instability occur.

## Infrastructure Alternatives

### Multipass apple-vz — not supported

```bash
multipass set local.driver=apple-vz
# set failed: Invalid setting 'local.driver=apple-vz': Invalid driver
```

Multipass does not support the `apple-vz` driver. QEMU remains the only backend,
so Multipass cannot expose Apple Silicon CPU features correctly.

### UTM with Apple Virtualization — correct solution

Use **UTM** with the **Apple Virtualization** backend instead of Multipass.
UTM's Apple Virtualization framework passes Apple Silicon CPU capabilities through
to the guest VM, which allows `onnxruntime` to detect CPU features correctly and
eliminates the SIGILL. The document loader SIGKILL is also resolved under proper
ARM64 virtualization.

Setup:
1. Install UTM from https://mac.getutm.app
2. Create a new VM — select **Virtualize** (not Emulate), **Linux**, Apple Virtualization backend.
3. Deploy K8s on the UTM VM.

## Resolution

Infrastructure: switch K8s node VMs from Multipass QEMU to **UTM Apple Virtualization**.
This resolves both the SIGILL (`embed_op`) and SIGKILL (`parse_op`) root causes at the
virtualization layer without requiring code changes.

### Related

Separately, `fastembed`/`onnxruntime` were removed and replaced with Qdrant server-side
IDF as an architectural improvement. See [qdrant-idf-transition.md](../qdrant-idf-transition.md).
