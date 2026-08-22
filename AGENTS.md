# Repository agent instructions

- Read `README.md` and the relevant `docs/` page before changing behavior.
- Never write to a configured 7 Days to Die install; it is read-only evidence.
- Never automate, request, print, or commit Unity credentials or license data.
- Preserve the class-142, disabled-module, game-version, collision, and
  fresh-client acceptance gates unless stronger evidence replaces them.
- Changes to UnityFS parsing require positive and negative generated fixtures.
- Changes to bundle generation require `make check test` plus a game-matched
  probe when Unity is available.
- Keep the consumer scaffold standalone; it must not depend on a relative
  checkout of another mod or repository.
- Do not add `Co-Authored-By` trailers or generated-with tool fluff to commits
  or pull requests.
