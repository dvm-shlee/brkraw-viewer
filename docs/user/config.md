# Config

The Config tab opens the BrkRaw `config.yaml` as text, with **Save**, **Backup**
(writes a time-stamped `.bak` copy next to the file) and **Reset** (back to the
BrkRaw defaults). The viewer keeps its own settings under the `viewer:` key of
that file, so teams can share one configuration.

## Viewer settings

```yaml
viewer:
  cache:
    memory_limit_mb: 1536   # ask when the data held would pass this many MB; 0 = never ask
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

The viewer's worker process reads the data; the window shows one frame at a time. When
a whole scan is read (a single-frame scan, the Timecourse window, or a converter hook
that returns every frame), the worker keeps that one copy so later frames and
timecourses take milliseconds. When you select another scan, the worker frees what it
held for the previous one.

Before it reads a scan, the viewer computes the size of that data from the scan
parameters (`VisuCoreSize` x `VisuCoreFrameCount` x word size in `visu_pars`; nothing is
read yet). When a converter hook is on and the hook can report the size of what it
returns (brkraw-sordino does), that size is used instead. If this size plus what the
worker still holds for other shown data is over `viewer.cache.memory_limit_mb`, it asks
whether to load it. If the size cannot be computed, it does not ask. The notice applies
to the Viewer tab only; Convert does not ask.

- **Yes** is remembered for that scan and reconstruction until you open another
  dataset, so the viewer does not ask again for it.
- **No** cancels the load. Selecting the scan or reconstruction again (or pressing
  Refresh) asks again.

Measured on one 298.6 MB scan (72 x 72 x 32 x 900, int16) with brkraw 0.6.1rc1: showing
one frame keeps the worker near 80 MB; reading the whole scan for the Timecourse
window holds one copy, about 1.1 times the data (worker about 370 MB, folder and zip);
the main window process does not copy the frames it receives. Reading every frame at
once (a converter hook) briefly needs about twice the data while the frames are handed
to the window.

The default is 1536 MB for everything held, chosen for a laptop with 8 GB of memory:
a 1 GB 2dseq opens without asking when little else is held. Earlier viewer versions
used 600 MB per scan, because with brkraw before 0.6.1 reading needed 3 to 5 times the
data size. Set it
from your computer's memory and your largest scan. `cache.enabled` and `cache.max_items`
were never read by the viewer; they are removed from the defaults and ignored if they
are still in an existing `config.yaml`.

## Disk cache

`viewer.cache.path` names a folder for cache files (relative paths are taken from the
BrkRaw config folder; `cache` there when the setting is empty). When you close the
viewer, it checks this folder and, if it holds files, asks whether to clear it. The
Timecourse window no longer writes files: the worker answers each voxel's series from
the data it holds (earlier versions wrote a temporary `.npy` file of the whole series
here).

For one-off external registry files, use CLI output override:

`brkraw viewer-registry add <path> -t /path/to/registry`
