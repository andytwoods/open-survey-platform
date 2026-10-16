/**
 * @osp/hooks-sandbox: researcher hooks (runtime-design.md §7a). `HookHost` runs the script
 * in a sandboxed iframe + worker; `HookRunner` turns engine `hook` effects into host calls
 * and records validated results with `resolve`. See README-free docs in each module.
 */

export * from './manifest.ts';
export * from './validate.ts';
export * from './host.ts';
export * from './runner.ts';
export { FRAME_CSP, FRAME_SCRIPT, FRAME_SCRIPT_HASH, FRAME_SRCDOC, LOCKED_GLOBALS, workerSource } from './sandbox-source.ts';
