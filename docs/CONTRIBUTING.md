# Contributing to ModelUnify

The GitHub repository is `AsafBSh/ModelUnity`; the product remains ModelUnify.
Use a feature branch and pull request to main. The intended protection requires
a PR, successful Source checks and resolved conversations, includes administrators,
and disallows force pushes/deletion. Live GitHub settings determine enforcement.
A literal read-only branch lock would prevent PR merges too, so use PR protection.

```powershell
git switch -c feature/describe-change
# Edit specific source files, version and CHANGELOG.md; validate locally.
git add <specific-files>
git commit -m "Describe resulting behavior"
git push -u origin feature/describe-change
gh pr create --base main
```

The initial upload bootstraps an empty main branch before protection is applied.
Subsequent updates use PRs. Requiring PRs without mandatory second-person approval
lets a sole maintainer merge their own PR after checks; GitHub disallows self-approval.

Source checks only compile project Python and reject tracked weights/runtimes/
generated assets. They do not replace local unit/browser/CUDA/portable checks.
Run relevant tests and report their evidence in the PR.

Publish code, configuration defaults, tests, docs, launcher/packaging sources,
product artwork and curated vendor source/licenses. Exclude weights, environments,
native binaries, projects, photos, generated assets, caches, installers and secrets.
The Word operating guide is an intentional document binary. See root .gitignore
and vendor/README.md. Do not replace patched snapshots with unpatched submodules.
