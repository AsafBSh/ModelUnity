# Contribute to ModelUnify

Use a feature branch and pull request to main. Main requires PRs and resolved
conversations, including administrators; force pushes and deletion are disabled.
There are no GitHub workflows or required automated status checks. Second-person
approval is optional so a sole maintainer can merge their own PR.

```powershell
git switch -c feature/describe-change
git add <specific-files>
git commit -m "Describe the change"
git push -u origin feature/describe-change
gh pr create --base main
```

Check relevant behavior locally and describe that evidence in the PR. Update
scripts/_version.py and CHANGELOG.md for each delivered change set. Publish source,
current user guides and upstream licenses. Keep weights, runtimes, private assets,
editor guidance, local tests and development reports out of Git.

## Record every update

Before delivery, increment scripts/_version.py and add a dated entry at the top of
CHANGELOG.md. Record the main behavior changes, relevant verification and any
remaining release limitation. Use patch versions for fixes and documentation,
minor versions for features and major versions for breaking changes. Keep earlier
entries and historical screenshot/build labels accurate. Include the version and
verification in the pull request and GitHub release notes.

## Prepare a source export

After committing the intended sources, run:

```powershell
.venv/Scripts/python.exe packaging/export_source.py --revision HEAD
```

The exporter reads only the selected Git commit and writes a fresh ZIP and
SHA-256 companion under dist/. It includes the current guides, screenshots and
upstream licenses, an EXPORT_INFO.json source-commit manifest and FILES.sha256.
It refuses linked files, weights, runtimes, secrets and private development paths.
Existing output files are preserved. Verify the checksum and extract to a new
folder, then follow docs/INSTALLATION.md.

This is a source package; it requires environment setup and does not contain a
portable Python runtime or installer. Publish it from the merged, protected main
commit and point its release tag at that same commit. Portable releases require
the separate build and relocation checks in BUILD_PORTABLE.md.
