# Config

The Config tab opens the BrkRaw `config.yaml` as text, with **Save**, **Backup**
(writes a time-stamped `.bak` copy next to the file) and **Reset** (back to the
BrkRaw defaults). The viewer keeps its own settings under the `viewer:` key of
that file, so teams can share one configuration.

## Viewer settings

```yaml
viewer:
  cache:
    memory_limit_mb: 600    # ask above this size in MB; 0 = never ask
    # path: cache           # optional, see "Disk cache" below
  registry:
    path: viewer/registry.jsonl
    # columns:              # registry window columns; each has key, title, width, hidden
    #   - {key: basename, title: Name, width: 180}
  worker:
    popup: true             # read at start-up and on Refresh; has no effect in this version
```

- `viewer.cache.memory_limit_mb`: the memory notice below.
- `viewer.registry.path`: the registry file, relative to the BrkRaw config folder
  unless it is absolute. A launch with `--registry`, the
  `BRKRAW_VIEWER_REGISTRY_PATH` variable or `viewer-registry -t` uses another file
  instead.
- `viewer.registry.columns`: the columns of the registry window and of
  `brkraw viewer-registry list`. A list you write replaces the default columns
  instead of adding to them.
- `viewer.worker.popup`: the viewer reads this value, but nothing in this version uses
  it; the worker log is available from the status bar.

The Convert tab also reads the BrkRaw layout settings (template, entries and slicepack
suffix) from the same file through `brkraw`.

Save writes `config.yaml` as it is. The memory limit and the worker setting are read
again when you press **Refresh** and when the viewer starts.

## Memory notice

The viewer keeps the whole 2dseq of the selected scan in its worker process so that
changing the frame takes milliseconds. Before it reads a scan, it computes the size of
that data from the scan parameters (`VisuCoreSize` x `VisuCoreFrameCount` x word size
in `visu_pars`; nothing is read yet). If the size is over
`viewer.cache.memory_limit_mb` it asks whether to load it. If the size cannot be
computed, it does not ask. The size comes from the stored data, so a converter hook that
changes the data shape can make the estimate inexact. The notice applies to the Viewer
tab only; Convert does not ask.

- **Yes** is remembered for that scan and reconstruction until you open another
  dataset, so the viewer does not ask again for it.
- **No** cancels the load. Selecting the scan or reconstruction again (or pressing
  Refresh) asks again.

Loading needs roughly 3.1 to 3.7 times the data size
in memory once loaded and up to about 5 times at the peak, measured on one 298.6 MB scan.

The default is 600 MB, chosen for a laptop with 8 GB of memory: a 500 MB 2dseq
opens without asking, and a 1 GB one is announced before anything is read. A scan just
above the default would need about 2.2 GB once loaded and about 3 GB at the peak
(3.7 and 5 times the data size, measured on one 298.6 MB scan). Set it from your
computer's memory and your largest scan; on a 16 GB computer 1024 is reasonable. `cache.enabled` and `cache.max_items`
were never read by the viewer; they are removed from the defaults and ignored if they
are still in an existing `config.yaml`.

## Disk cache

For multi-frame data, the Timecourse window writes a temporary `.npy` file of the whole
series under `~/.brkraw/cache/viewer`. The viewer removes it when you close the Timecourse
window or select another scan or dataset, and builds a new one when the source file
changes. When you close the viewer, it checks the folder given by `viewer.cache.path`
(relative paths are taken from the BrkRaw config folder; `cache` there when the setting
is empty) and, if it holds files, asks whether to clear it. The Timecourse file location
is fixed and does not follow `viewer.cache.path`.

For one-off external registry files, use CLI output override:

`brkraw viewer-registry add <path> -t /path/to/registry`
