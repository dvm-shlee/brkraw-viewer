# Config

The Config tab opens the BrkRaw `config.yaml` as text, with **Save**, **Backup**
(writes a time-stamped `.bak` copy next to the file) and **Reset** (back to the
BrkRaw defaults). The viewer keeps its own settings under the `viewer:` key of
that file, so teams can share one configuration.

## Viewer settings

```yaml
viewer:
  cache:
    memory_limit_mb: auto   # auto = 16 % of the installed memory (at least 512 MB); a number = MB; 0 = never ask
    hook_memory_percent: 25 # with a converter hook on: ask when its peak passes this % of the installed memory; 0 = off
    # path: cache           # optional, see "Disk cache" below
  registry:
    path: viewer/registry.jsonl
    # columns:              # registry window columns; each has key, title, width, hidden
    #   - {key: basename, title: Name, width: 180}
  worker:
    popup: true             # read at start-up and on Refresh; has no effect in this version
```

- `viewer.cache.memory_limit_mb`: the memory notice below. Missing or `auto`: 16 % of
  the installed memory, at least 512 MB. A number is used as written (an older config
  that still holds `1536` keeps that number); `0` never asks.
- `viewer.cache.hook_memory_percent`: the hook notice ("Converter hook peak" below).
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

- **Yes** is remembered for that scan and reconstruction, with the converter hook and
  hook options that were on, until you open another dataset, so the viewer does not ask
  again for it. Turning a hook on, or changing its options, is a different load and asks
  by itself.
- **No** cancels that load only. Turning the hook off and on again, pressing **Apply** in
  Hook Options, selecting the scan or reconstruction again, or pressing Refresh asks
  again; a plain load, or a load with other hook options, is not blocked by an earlier No.

Measured on one 298.6 MB scan (72 x 72 x 32 x 900, int16) with brkraw 0.6.1rc1: showing
one frame keeps the worker near 80 MB; reading the whole scan for the Timecourse
window holds one copy, about 1.1 times the data (worker about 370 MB, folder and zip);
the main window process does not copy the frames it receives. Reading every frame at
once (a converter hook) briefly needs about twice the data while the frames are handed
to the window.

The limit is `auto` unless you set a number: 16 % of the memory installed in the computer
(8 GB gives 1,310 MB, 16 GB gives 2,621 MB), but never less than 512 MB. The viewer reads
the installed memory when it starts and on Refresh (Windows: `GlobalMemoryStatusEx`; if the
memory cannot be read, 4 GB is assumed and the notice says so). A number in
`viewer.cache.memory_limit_mb` always wins over the automatic value, including the `1536`
that earlier versions wrote as the default; `0` turns the question off. Earlier viewer
versions used 600 MB per scan, because with brkraw before 0.6.1 reading needed 3 to 5 times
the data size.

Going over the limit is a warning, not a stop: the notice says how much would be held, the
limit and where the limit comes from (the percentage and the installed memory, or your
setting, and the 512 MB minimum when it applies). **Yes** continues, **No** cancels that load.
`cache.enabled` and `cache.max_items` were never read by the viewer; they are removed from
the defaults and ignored if they are still in an existing `config.yaml`.

### Converter hook peak

A converter hook such as brkraw-sordino reconstructs one volume at a time, so what matters
is not only the size of the result. When the hook can report its peak memory use
(`peak_nbytes`; brkraw-sordino does), the viewer compares **that peak plus what it already
holds for other data** with `viewer.cache.hook_memory_percent` of the installed memory
(default 25 %, so 4 GB on a 16 GB computer). The peak the hook reports already contains one
volume's reconstruction, the result image (every frame it returns) and three cached frames,
so the viewer does not add the image again. If it is over, or the data held is over the
memory limit above, the viewer asks **once**: the notice shows the peak, its percentage of
the installed memory and the share it asks above. Yes and No work as for the memory limit.

- `0` turns this question off; `memory_limit_mb: 0` (never ask) turns it off as well.
  A value of 100 or more means "only ask above the installed memory"; a value that is not a
  number uses 25.
- The share should be larger than the 16 % automatic limit, otherwise the memory limit
  question already covers it.
- When the peak is over the hook's own limit (brkraw-sordino: half of the installed memory
  unless you set another), the hook will refuse the load by itself and tell you what to
  change, so the viewer does not ask first; you see the hook's message.
- A hook that does not report a peak, a load whose cache already exists (its peak is the
  image and three cached frames) and a plain load without a hook are not affected.
- The 25 % is a proposal, not a measured value. The hook's estimate is at most twice the
  measured use, so the notice can come before the memory is really short.

## Disk cache

`viewer.cache.path` names a folder for cache files (relative paths are taken from the
BrkRaw config folder; `cache` there when the setting is empty). When you close the
viewer, it checks this folder and, if it holds files, asks whether to clear it. The
Timecourse window no longer writes files: the worker answers each voxel's series from
the data it holds (earlier versions wrote a temporary `.npy` file of the whole series
here).

For one-off external registry files, use CLI output override:

`brkraw viewer-registry add <path> -t /path/to/registry`
