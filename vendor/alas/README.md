# vendor/alas

This subtree is a verbatim copy of selected files from Alas
([LmeSzinc/AzurLaneAutoScript](https://github.com/LmeSzinc/AzurLaneAutoScript))
needed to run `NemuIpcImpl` and its transitive dependencies.

## Origin

Imported by `dev_tools/vendor_alas.py` from a sparse-checkout of Alas master.

```text
seed:       module/device/method/nemu_ipc.py
namespaces: module.*, deploy.*
```

The vendor script walks the import graph starting from the seed, copies each
reachable source file into `vendor/alas/...`, and rewrites top-level imports:

```text
from module.x        ->  from vendor.alas.module.x
from deploy.x        ->  from vendor.alas.deploy.x
```

Nothing else is changed. Logic is preserved bit-for-bit.

## Discipline

- **Do not modify any file inside `vendor/alas/`.** This includes adding
  comments, reformatting, "small fixes", etc. The only transformation
  ever applied is the import-prefix rewrite by `dev_tools/vendor_alas.py`.
- To extend what is vendored, edit `dev_tools/vendor_alas.py` (e.g., add a
  new seed or namespace) and re-run with `--clean`. Never hand-edit.
- To wrap or extend Alas behavior, write your code in `core/` and import
  the vendored names from there. Wrappers belong in `core/input_backend/`
  for IPC, `core/vision/` for OCR, etc.

## License

Alas is licensed under GPL-3.0. The vendored files retain their original
copyright and license. See https://github.com/LmeSzinc/AzurLaneAutoScript
for the upstream LICENSE file. Anyone redistributing this project must
comply with GPL-3.0 obligations for the vendored content.

## Regenerating

From the project root:

```powershell
# 1. (one-time) sparse-checkout Alas into _tmp_alas/
git clone --depth 1 --filter=blob:none --sparse https://github.com/LmeSzinc/AzurLaneAutoScript.git _tmp_alas
git -C _tmp_alas sparse-checkout set module deploy

# 2. rebuild vendor/alas/
python dev_tools/vendor_alas.py --clean
```

The resulting tree should be importable as `vendor.alas.module.*` and
`vendor.alas.deploy.*`.
