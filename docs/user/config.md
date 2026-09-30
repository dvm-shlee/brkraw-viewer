# Config

The Config tab keeps **viewer defaults in one place** so teams can align on
layout and registry preferences without editing YAML by hand.

## Common settings

- Viewer display options
- Column layout for registry tables
- Conversion layout defaults
- Viewer memory notice (`viewer.cache.memory_limit_mb`, below)

Changes are written to `config.yaml` and applied at the next load.

## Memory notice

The viewer keeps the whole 2dseq of the selected scan in its worker process so that
changing the frame takes milliseconds. Before it reads a scan, it computes the size of
that data from the scan parameters (nothing is read yet). If the size is over
`viewer.cache.memory_limit_mb` it asks whether to load it; the answer is remembered for
that scan until you open another dataset. Loading needs roughly 3.1 to 3.7 times the data size
in memory once loaded and up to about 5 times at the peak, measured on one 298.6 MB scan.

```yaml
viewer:
  cache:
    memory_limit_mb: 1024   # ask above this size in MB; 0 = never ask
```

The default, 1024 MB, is provisional: the 298.6 MB scan that was measured stays below
it, and a scan just above it would need about 3.7 GB once loaded and about 5 GB at the
peak, which a 16 GB computer can still hold. Set it from your computer's memory and your
largest scan. `cache.enabled` and `cache.max_items`
were never read by the viewer; they are removed from the defaults and ignored if they
are still in an existing `config.yaml`. `viewer.cache.path`, if set, is only the disk
cache folder that the viewer offers to clear when it closes.

For one-off external registry files, use CLI output override:

`brkraw viewer-registry add <path> -t /path/to/registry`
