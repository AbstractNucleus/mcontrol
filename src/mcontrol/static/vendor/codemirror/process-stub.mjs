/*
 * Minimal stub for esm.sh's /node/process.mjs side-effect import.
 * The vendored @codemirror/lang-* bundles reference process.env.LOG as a
 * debug flag from the lezer parser; providing an empty env object is
 * sufficient to keep those references inert in the browser.
 */
const process = { env: {} };
export default process;
export const env = process.env;
