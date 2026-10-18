// Where the end-to-end run builds and serves the pages: a directory of its own, not build/.
// `make check` rebuilds build/ (emptying it), and a preview serving that would 404 every
// asset from then on. One per port, so runs beside each other keep theirs too.
export const E2E_PORT = Number(process.env.OSP_E2E_PORT ?? 4317);
export const E2E_OUT_DIR = new URL(`../../../.build/builder-e2e/${E2E_PORT}/`, import.meta.url);
