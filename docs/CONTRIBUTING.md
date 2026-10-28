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
