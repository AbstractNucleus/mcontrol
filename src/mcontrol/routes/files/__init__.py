"""Files-routes package.

`routes/files.py` was split into per-concern submodules (decision 044).
Each submodule owns its own `APIRouter`; this package merges them into
a single `router` so `from mcontrol.routes.files import router` keeps
working in `main.create_app`.

Path-safety contract (mirrors slice 5 plan; applies to every endpoint):

1. Resolve `(<dir>) / operator_path` and refuse `..` traversal.
2. Walk every component with `Path.is_symlink()` — refuse to follow
   any segment that is a symlink. Symlinks are still rendered in
   listings (with a marker) but never traversed for read or write.
3. Sub-path check: the resolved target must live inside the resolved
   row `dir`. HTTP 400 otherwise.
4. Special files (S_ISBLK / S_ISCHR / S_ISFIFO / S_ISSOCK) are
   skipped from listings and rejected at endpoints.
5. Upload + mkdir filenames are operator-controlled; refuse `/`, `\\`,
   `..`, `.`, empty, and null-byte names before anything touches disk.
6. Delete refuses `path=""` (the server's bind-mount root is sacred)
   and refuses to follow symlinks — `os.unlink` removes the link entry,
   never the target.
"""

from fastapi import APIRouter

from mcontrol.routes.files import mutate, search, tree, view, write

router = APIRouter()
router.include_router(tree.router)
router.include_router(view.router)
router.include_router(write.router)
router.include_router(mutate.router)
router.include_router(search.router)

__all__ = ["router"]
