# Local KRDICT data

Hanly's dictionary is built from the official KRDICT release, which is licensed
and **not redistributable through this repository**. Git tracks this README and
nothing else here: the source archive, the database, the compressed asset, the
producer manifest, and the validation report are all ignored.

What the repository keeps is the *recipe* — the tooling in `tools/krdict/` plus
the commands below — so anyone with the official archive can reproduce a
byte-identical database. That is why this file exists even though everything it
describes lives only on your machine.

```
data/
  source/     the official ZIP, downloaded by hand
  generated/  krdict.sqlite3, the .sqlite3.zst asset, the producer manifest
  reports/    validation evidence
```

## Building it

Put the official archive in `source/`, then run the three tools in order. Each
takes the source identity explicitly — nothing is inferred from a filename.

```powershell
$Archive = 'data\source\<official-krdict-archive>.zip'
$Version = '20260819-v1'          # <source-date>-v<n>
$SourceDate = '2026-08-19'        # the date the archive was published

.\.venv\Scripts\python.exe tools\krdict\build_seed.py $Archive `
  --output data\generated\krdict.sqlite3 `
  --source-date $SourceDate `
  --resource-version $Version `
  --build-date (Get-Date -Format 'yyyy-MM-dd')

.\.venv\Scripts\python.exe tools\krdict\validate_seed.py `
  data\generated\krdict.sqlite3 `
  --source $Archive `
  --report "data\reports\krdict-$Version.json"

.\.venv\Scripts\python.exe tools\krdict\package_resource.py `
  data\generated\krdict.sqlite3 `
  --output "data\generated\krdict-$Version.sqlite3.zst" `
  --resource-version $Version `
  --source-date $SourceDate `
  --manifest "data\generated\krdict-$Version.resource.json"
```

`--build-date` is an explicit argument so that repeating a build with the same
source and the same arguments produces the same bytes. Pin it to a fixed date
when reproducing an existing release rather than making a new one.

`validate_seed.py` also accepts `--expect-entries`, `--expect-senses`, and
`--expect-sanitized-bytes` to assert counts you already know. Use them when
reproducing a known release; omit them when building from a new archive, where
the counts are what you are trying to discover.

To look at an archive without building anything:

```powershell
.\.venv\Scripts\python.exe tools\krdict\inspect.py <archive.zip> --compact
```

## Known irregularities in the official source

These are properties of the published data, not bugs, and the tooling handles
each one deliberately:

- **Raw entry IDs are reused.** `LexicalEntry` IDs are not unique across the
  archive, so `(source, source_id)` is indexed but not unique. `entries.id` is
  the only identity, and every child foreign key uses it.
- **A few XML-illegal `0x08` bytes** appear in the text. They are replaced in
  the parser's byte stream only; the archive on disk is never rewritten, and
  `validate_seed.py` reports how many were replaced.
- **`subjectCategiory` is misspelled** in the source. The parser matches the
  misspelling, because matching the correct spelling silently drops every
  subject category.

## Producing the release asset in CI

The `Build KRDICT resource` workflow never reads or uploads a source archive
from this repository. Dispatch it with the official HTTPS download URL and that
archive's exact SHA-256; the runner downloads it, verifies the digest before
parsing, and uploads only the compressed resource, the producer manifest, and
the validation report. Keep any local copy under the ignored `source/`
directory for inspection only.
