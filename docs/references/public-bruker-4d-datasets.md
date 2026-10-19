# Public Bruker ParaVision raw datasets with a 4D scan (viewer checklist sections 3-5)

Retrieved 2026-10-19 (last fetch 18:30 UTC). Only listings and metadata were fetched: GitHub tree API, raw
`metadata.yaml` files and Git LFS pointer files; Zenodo record API (`/api/records/<id>`), Zenodo version lists, and the
Zenodo zip directory listing (`/api/records/<id>/files/<zip>/container`, entry names and sizes only); DataCite and
Crossref for identifiers; one open-access paper page (PMC7026488). No data archive and no file inside an archive was
downloaded.

Repetition counts are NOT confirmed for any candidate. A time-series scan is named here from a listing or from the
record's stated protocol; the number of repetitions (`PVM_NRepetitions` in `method`, `NR` in `acqp`,
`VisuCoreFrameCount` in `visu_pars`) is to be confirmed after the fetch (tomorrow), before the checklist run relies on it.

Selection rule: a candidate is listed only if a time-series scan can be named. Excluded datasets are listed at the end.

## Candidates

### 1. BrkRaw/brkraw-dataset, `PV5.1/UNC_PV5.1_BOLD-EPI_TurboRARE.zip` (in vivo rat, BOLD EPI)
- URL: https://github.com/BrkRaw/brkraw-dataset (folder `PV5.1/`, Git LFS object)
- Licence: CC BY 4.0. Source says: `license: CC BY 4.0` [loc: `PV5.1/UNC_PV5.1_BOLD-EPI_TurboRARE.metadata.yaml`].
- ParaVision: 5.1. Source says: `notes: Paravision 5.1 example dataset` [loc: same metadata.yaml].
- Size: 231,545,025 bytes. Source says: `size 231545025`, `oid sha256:2ea0a24a3ba333440b921fa19ccf8b78e31322c715e95d0a71d50360fa1fb879` [loc: LFS pointer `PV5.1/UNC_PV5.1_BOLD-EPI_TurboRARE.zip`].
- Time-series scan: scan 11, `EPI`; the file name says BOLD-EPI. Source says: `subject: SD-rat`, `scans: 3: FLASH, 4: FieldMap, 9: TurboRARE, 11: EPI` [loc: metadata.yaml]; institution Center for Animal MRI, UNC at Chapel Hill.
- Verified by: GitHub tree API listing of the repository (two datasets, PV5.1 and PV6.0.1), metadata.yaml and LFS pointer read.
- Note: BOLD EPI on a living rat is a real time series by protocol; repetition count of scan 11 to be confirmed after the fetch. Fetch needs Git LFS (`git lfs pull`), since the zip in the git tree is only a pointer.

### 2. BrkRaw/brkraw-dataset, `PV6.0.1/UNC_PV6.0.1_FLASH_TurboRARE_EPI.zip` (agar phantom, EPI)
- URL: https://github.com/BrkRaw/brkraw-dataset (folder `PV6.0.1/`, Git LFS object)
- Licence: CC BY 4.0 [loc: `PV6.0.1/UNC_PV6.0.1_FLASH_TurboRARE_EPI.metadata.yaml`].
- ParaVision: 6.0.1. Source says: `notes: Paravision 6.0.1 example dataset` [loc: metadata.yaml].
- Size: 7,344,749 bytes; `oid sha256:f889c7618d7afd5a42ab5302746f17d0bd2fcf44ae77eee1946f18ff9036523d` [loc: LFS pointer].
- Time-series scan: scan 11, `EPI`. Source says: `subject: phantom`, scans `3: FLASH, 6: RARE, 7: FLASH, 10: FieldMap, 11: EPI`, comment `50ml conical tube with 2% agar phantom, imaged with high-susceptibility materials on the tube surface` [loc: metadata.yaml].
- Verified by: metadata.yaml and LFS pointer read.
- Note: a phantom, so no physiological signal; that scan 11 is repeated (4D) follows only from the EPI label and is to be confirmed after the fetch. Useful as a 7 MB smoke test for the PV6 parser path.

### 3. Zenodo 3823441, ParaVision Mouse, Rat, and Lemur Testing Data for SAMRI (v0.4)
- URL: https://zenodo.org/records/3823441 (DOI 10.5281/zenodo.3823441; v0.2 is DOI 10.5281/zenodo.3234924, both checked on DataCite, same title, 2019)
- Licence: CC BY 4.0 [loc: Zenodo API `metadata.license.id = cc-by-4.0`].
- ParaVision: 6.0.1. Source says the data were acquired "with ParaVision 6.0.1." [loc: Ioanas et al. 2020, Frontiers in Neuroinformatics, DOI 10.3389/fninf.2020.00005, Methods; DOI checked on Crossref: title, journal, 2020-02-11, authors Ioanas, Marks, Garin, Dhenain, Yanik, Rudin; read on PMC7026488]. The paper cites the archive as Ioanas et al. 2019a with the v0.2 DOI 10.5281/zenodo.3234924 [loc: reference list]; quoted text checked in the Europe PMC full-text XML of PMC7026488.
- Size: 2,349,556,936 bytes, one file `samri_bindata-0.4.tar.xz`, md5 5c8a0eef55ae79c2ad2bcb4bb34ccddd [loc: Zenodo API files]. v0.2: 1,706,708,232 bytes.
- Time-series scan: resting-state BOLD EPI of the rat study folder `20171106_184345_21_1_1`. Source says the record keywords include `fMRI`, `BOLD`, `geEPI`, `seEPI` [loc: Zenodo API keywords]; the paper gives an example for "a resting-state scan acquired with an EPI sequence resolving BOLD contrast" whose strings are taken from "the rat data identified in the archive by the 20171106_184345_21_1_1 directory name" [loc: paper section 2.1, Operator Guidelines]. The scan number inside that study folder is not stated. Note: the paper takes its example strings (one of them for a resting-state BOLD EPI scan) from that folder; that the folder holds such a scan is inferred from this, not listed.
- Verified by: Zenodo API record and version list, DataCite, Crossref, PMC full text (open access). The tar.xz cannot be listed without downloading it, so the folder name comes from the paper and is not checked against the archive.
- Note: in vivo BOLD at PV 6.0.1, but 2.3 GB to fetch and the paper describes the v0.2 archive; that the folder is still in v0.4 is an assumption.

### 4. Zenodo 13688071, DHMC opto-fMRI Pilot Raw Bruker ParaVision Data
- URL: https://zenodo.org/records/13688071 (DOI 10.5281/zenodo.13688071, checked on DataCite, 2024)
- Licence: CC BY 4.0 [loc: Zenodo API].
- ParaVision: not stated (the title says Bruker ParaVision data).
- Size: 384,699,004 bytes, one file `dhmcps_brudata-0.1.tar.xz`, md5 b3080b34ae031ae0e9382413ed96354b [loc: Zenodo API files].
- Time-series scan: opto-fMRI scans, named from the stated protocol only. Source says: "Pilot data used to develop an opto-fMRI protocol at Dartmouth Hitchcock Medical Center." [loc: Zenodo record description]; creator Ioanas, Horea-Ioan (Dartmouth College).
- Verified by: Zenodo API record and DataCite. The tar.xz cannot be listed without downloading it; no scan number, subject or ParaVision version is stated.
- Note: in vivo fMRI is the stated purpose, so a BOLD time series is expected; mid-size (385 MB).

### 5. Zenodo 13683103 (v2), DCE-MRI of focused-ultrasound BBB opening in mice
- URL: https://zenodo.org/records/13683103 (DOI 10.5281/zenodo.13683103, checked on DataCite, 2024). Other versions: 10992070 (v1, 2,160,263,657 bytes) and 23351644 (v3, published 2026-10-13, zip 6,884,261,909 bytes).
- Licence: CC BY 4.0 [loc: Zenodo API].
- ParaVision: not stated. Source says: acquired on a "9.4T Bruker BioSpec USR 94/30 scanner" [loc: record description].
- Size: 4,132,633,210 bytes (`ISIBrno_FUS_DCEMRI_v2.zip`).
- Time-series scan: DCE scans with the RF-spoiled 3D FLASH GASOS sequence [loc: record description]. The zip listing shows six ParaVision study folders under `ISIBrno_FUS_DCEMRI/Real data/` (for example `20231123_172531_fufatko02_02_1_3`, holding `subject`, `ResultState`, `ScanProgram.scanProgram` and scan folders with `acqp`, `method`, `fid`, `visu_pars`, `pdata/1/2dseq`); ten scan folders carry a `traj` file (for example scans 2 and 3 of `20231123_172531_fufatko02_02_1_3`, `fid` 190,464,000 and 196,608,000 bytes) [loc: Zenodo container listing, 770 entries].
- Verified by: Zenodo API record, version list and zip directory listing (names and sizes only).
- Note: the scans with `traj` are taken to be the golden-angle DCE scans (inference from the trajectory file and the large `fid`). Their `pdata/1/2dseq` is only 327,680 bytes, so the ParaVision reconstruction is probably not the dynamic series, and the time series may exist only as raw k-space needing offline reconstruction. A weak fallback for a viewer that reads `2dseq`.

## Recommendation

Recommend candidate 1 (brkraw-dataset `PV5.1/UNC_PV5.1_BOLD-EPI_TurboRARE.zip`, scan 11) for checklist sections 3-5:
an in vivo rat BOLD EPI time series (preferred over a phantom), CC BY 4.0, 231 MB, declared ParaVision 5.1 and a named
scan number, from the BrkRaw project's own test data. Use candidate 2 (7 MB PV 6.0.1 phantom, scan 11) only as a quick
smoke test of the PV6 path, not as the checklist's time series. If candidate 1 turns out not to be 4D after the fetch,
fall back to candidate 3 (in vivo BOLD, PV 6.0.1, 2.3 GB).

Still open after the fetch (tomorrow): the repetition count of the chosen scan (it must be greater than 1 for the run to
count as 4D), and the actual ParaVision version in the study files.

## Excluded

- Zenodo 231147 (Boussida et al., raw BOLD fMRI of 12 rats, CC BY 4.0, 1,034,709,277 bytes, one `.rar`): the protocol
  is a stated BOLD time series, but the record does not say the files are ParaVision study folders and a `.rar` cannot
  be listed without downloading it.
- Zenodo 4048286 and 4048253 (BrukerAPI test data, PV 5.1 and 6.0.1, CC BY 4.0): EPI sequences are listed, but the
  zip listings do not map scan numbers to sequences and the PV 6.0.1 set is a phantom (`lego_phantom` folder name), so no
  time-series scan can be named.
- Zenodo 10537319 (rat resting-state fMRI with electrophysiology): fMRI is shared as `fMRI_nii.zip` (NIfTI), not as
  ParaVision raw data. Zenodo 14534419 and 14534751 (mouse rsfMRI): NIfTI files.
