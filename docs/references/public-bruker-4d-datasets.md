# Public Bruker ParaVision raw datasets with a 4D scan (viewer checklist sections 3-5)

Retrieved 2026-10-19. Nothing was downloaded beyond listings (Zenodo API metadata, GitHub API directory listings, Git LFS pointer files). Archive contents were not opened, so scan numbers inside archives are NOT verified unless stated.

## Candidates

### 1. BrkRaw/brkraw-dataset, PV5.1 `UNC_PV5.1_BOLD-EPI_TurboRARE.zip`
- URL: https://github.com/BrkRaw/brkraw-dataset (folder `PV5.1/`; Git LFS)
- Licence: CC BY 4.0 (metadata.yaml field `license: CC BY 4.0`; repository LICENSE file is the CC BY 4.0 text)
- ParaVision: 5.1 (metadata `notes: Paravision 5.1 example dataset`; folder name)
- Size: 231,545,025 bytes (LFS pointer `size` field)
- 4D scan: scan 11, listed as EPI (BOLD-EPI per file name); subject SD-rat. Other scans: 3 FLASH, 4 FieldMap, 9 TurboRARE.
- Verified by: read `PV5.1/UNC_PV5.1_BOLD-EPI_TurboRARE.metadata.yaml` and the `.zip` LFS pointer. Repetition count of scan 11 not checked (BOLD EPI by name).

### 2. BrkRaw/brkraw-dataset, PV6.0.1 `UNC_PV6.0.1_FLASH_TurboRARE_EPI.zip`
- URL: https://github.com/BrkRaw/brkraw-dataset (folder `PV6.0.1/`; Git LFS)
- Licence: CC BY 4.0 (metadata.yaml)
- ParaVision: 6.0.1 (metadata)
- Size: 7,344,749 bytes (LFS pointer)
- 4D scan: scan 11, EPI; subject is a 2% agar phantom (not a living subject); other scans 3 FLASH, 6 RARE, 7 FLASH, 10 FieldMap.
- Verified by: metadata.yaml and LFS pointer read. Repetition count not checked. Small, so quick to fetch.

### 3. Zenodo 231147, raw BOLD fMRI of 12 rats (Boussida et al.)
- URL: https://zenodo.org/records/231147 (DOI 10.5281/zenodo.231147)
- Licence: CC BY 4.0 (Zenodo API `license.id`)
- ParaVision: not stated (4.7T Bruker Biospec 47/40, AVANCE III console)
- Size: 1,034,709,277 bytes, one file `RawData-ResearchArticleBoussidaPlosOne.rar`
- 4D scan: two-shot GE-EPI, 10 axial slices, 64x64, TR 1000 ms, block design 25 s rest / 25 s stimulation x 8 (record description). Expected as a time series; the description does not say the files are ParaVision study folders.
- Verified by: Zenodo API record (metadata and file list). The .rar was not opened, so the on-disk format is unverified. Risk: .rar needs `unrar`.

### 4. Zenodo 3823441, ParaVision Mouse, Rat, and Lemur Testing Data for SAMRI
- URL: https://zenodo.org/records/3823441 (DOI 10.5281/zenodo.3823441)
- Licence: CC BY 4.0 (Zenodo API)
- ParaVision: version not stated; description says "stored in the Bruker ParaVision format"
- Size: 2,349,556,936 bytes, single file `samri_bindata-0.4.tar.xz`
- 4D scan: not stated in the record ("diverse protocols"); presumably includes fMRI for SAMRI, not verified.
- Verified by: Zenodo API record only. Large with unlisted contents: poor first choice.

### 5. Zenodo 13683103 (v2) / 10992070 (v1), FUS DCE-MRI in mice
- URL: https://zenodo.org/records/13683103 (DOI 10.5281/zenodo.13683103); v1 https://zenodo.org/records/10992070
- Licence: CC BY 4.0 (Zenodo API)
- ParaVision: not stated (9.4T Bruker BioSpec USR 94/30)
- Size: 4,132,633,210 bytes (v2 zip); v1 2,160,263,657 bytes
- 4D scan: dynamic 3D FLASH DCE series would be 4D, but the record mixes real and simulated data and the format (ParaVision or not) is not stated. Not verified.
- Verified by: Zenodo API record; a data description PDF exists but was not read.

## Recommendation

Recommend candidate 2 (brkraw-dataset PV6.0.1, 7.3 MB) to start the checklist: tiny, CC BY 4.0, maintained by the BrkRaw project for its own conversion tests, declared ParaVision 6.0.1 and a declared EPI scan 11. Then candidate 1 (PV5.1 rat BOLD-EPI, 231 MB) as a second dataset with a real BOLD time series. Both need Git LFS to fetch (the zip in the git tree is only a pointer), per the repository README.

Caveats: (a) "EPI = 4D" is inferred from the sequence type; confirm the repetition count (PVM_NRepetitions in the method file) after the first fetch. (b) Candidate 2 is a phantom, so physiology-dependent checks are not exercised; use candidate 1 for those. (c) Candidates 3-5 are unverified fallbacks.
