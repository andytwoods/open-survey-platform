// Page entry `preview-frame`: one device frame of the preview (the participant app in
// preview mode). It takes no API base or CSRF (planning/pages-split.md D10) and talks to
// the builder page only by checked postMessage (src/lib/preview/bridge.ts).
import { autoMount, defineFramePage } from '#lib/host/mount.js';
import PreviewFrame from '#lib/preview/PreviewFrame.svelte';

export const mount = defineFramePage('preview-frame', PreviewFrame);

autoMount(mount, { name: 'preview-frame', frame: true });
